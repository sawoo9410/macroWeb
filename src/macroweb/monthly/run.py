"""Monthly learning loop v1 (PLAN §12, ADR-0012): thesis scoring + calibration, source credibility update
(Bayesian, prior strength 20, refutations discounted by the stratum error rate when Q7 exists — 0 for now),
graph pruning, cost report, quality trend, the investment-diary 'macro background' digest and a retrospective md.
Verifier retraining (§12-3) needs eval/verify labels and is reported as pending."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from macroweb.analysis.thesis import auto_score, calibration, list_theses
from macroweb.graph.analysis import hubs
from macroweb.graph.store import active_edges, expire_edges, graph_counts
from macroweb.paths import ROOT, digests_dir

PRIOR_STRENGTH = 20
FACT_LABELS = ("VERIFIED", "CORROBORATED")
REFUTED_LABELS = ("DEBUNKED", "DISPUTED")
MONTHLY_DIR = ROOT / "reports" / "monthly"


def month_bounds(month: str) -> tuple[str, str]:
    y, m = (int(x) for x in month.split("-"))
    start = datetime(y, m, 1, tzinfo=UTC)
    end = datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=UTC)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


@dataclass
class MonthlyResult:
    month: str
    theses: dict[str, Any] = field(default_factory=dict)
    credibility: list[dict[str, Any]] = field(default_factory=list)
    graph: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    quality: list[dict[str, Any]] = field(default_factory=list)
    extraction_errors: list[tuple[str, int]] = field(default_factory=list)
    report: Path | None = None
    macro_background: Path | None = None
    pending: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "theses": self.theses,
            "credibility_updates": len(self.credibility),
            "graph": self.graph,
            "cost": self.cost,
            "quality_weeks": len(self.quality),
            "report": str(self.report) if self.report else None,
            "macro_background": str(self.macro_background) if self.macro_background else None,
            "pending": self.pending,
        }


def update_credibility(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    *,
    stratum_error: dict[str, float] | None = None,
    now_iso: str,
) -> list[dict[str, Any]]:
    """credibility = (20·prior₀ + confirmed − refuted·(1 − e)) / (20 + confirmed + refuted) recomputed from the
    **whole history up to `end`** (final labels + human decisions), so re-running a month is idempotent. prior₀ is
    the configured tier prior (sources.yaml credibility_prior). The month's own counts are reported alongside."""
    from macroweb.config import TIER_PRIOR, load_sources

    stratum_error = stratum_error or {}
    prior0 = {
        s.id: float(s.credibility_prior if s.credibility_prior is not None else TIER_PRIOR[s.tier])
        for s in load_sources().sources
    }

    def counts(since: str | None) -> dict[str, dict[str, float]]:
        per: dict[str, dict[str, float]] = defaultdict(lambda: {"confirmed": 0.0, "refuted": 0.0, "n": 0.0})
        where = "first_seen < ? AND label IS NOT NULL" + (" AND first_seen >= ?" if since else "")
        args: tuple[str, ...] = (end, since) if since else (end,)
        for r in conn.execute(f"SELECT signals_json, label, stratum FROM claim WHERE {where}", args):  # noqa: S608
            src = json.loads(r["signals_json"] or "{}").get("source_id")
            if not src:
                continue
            per[src]["n"] += 1
            if r["label"] in FACT_LABELS:
                per[src]["confirmed"] += 1
            elif r["label"] in REFUTED_LABELS:
                per[src]["refuted"] += 1 - float(stratum_error.get(r["stratum"] or "", 0.0))
        dwhere = "q.decided_at < ? AND q.decision IN ('approve', 'reject')" + (
            " AND q.decided_at >= ?" if since else ""
        )
        for r in conn.execute(
            f"SELECT q.decision, c.signals_json FROM review_queue q JOIN claim c ON c.id = q.claim_id WHERE {dwhere}",  # noqa: S608
            args,
        ):
            src = json.loads(r["signals_json"] or "{}").get("source_id")
            if src:
                per[src]["confirmed" if r["decision"] == "approve" else "refuted"] += 1
        return per

    total, month = counts(None), counts(start)
    out = []
    for src, c in sorted(total.items()):
        row = conn.execute("SELECT credibility FROM source_stats WHERE source_id = ?", (src,)).fetchone()
        if row is None:
            continue
        p0 = prior0.get(src, float(row["credibility"] if row["credibility"] is not None else 0.5))
        prev = float(row["credibility"] if row["credibility"] is not None else p0)
        new = (PRIOR_STRENGTH * p0 + c["confirmed"] - c["refuted"]) / (
            PRIOR_STRENGTH + c["confirmed"] + c["refuted"]
        )
        new = round(min(0.99, max(0.05, new)), 4)
        conn.execute(
            "UPDATE source_stats SET credibility = ?, n_claims = ?, n_confirmed = ?, n_refuted = ?, updated_at = ? WHERE source_id = ?",
            (new, int(c["n"]), int(c["confirmed"]), int(round(c["refuted"])), now_iso, src),
        )
        m = month.get(src, {"confirmed": 0.0, "refuted": 0.0, "n": 0.0})
        out.append(
            {
                "source": src,
                "prior": prev,
                "prior0": p0,
                "credibility": new,
                "confirmed": m["confirmed"],
                "refuted": round(m["refuted"], 2),
                "claims": int(m["n"]),
                "total_confirmed": c["confirmed"],
                "total_refuted": round(c["refuted"], 2),
            }
        )
    conn.commit()
    return out


def cost_report(conn: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    days = conn.execute(
        "SELECT substr(submitted_at, 1, 10) AS d, SUM(n_requests) AS calls, ROUND(SUM(cost_usd), 3) AS est FROM llm_batch WHERE submitted_at >= ? AND submitted_at < ? GROUP BY d ORDER BY d",
        (start, end),
    ).fetchall()
    runs = conn.execute(
        """SELECT job, COUNT(*) AS n, SUM(status = 'ok') AS ok, SUM(tokens_in) AS tin, SUM(tokens_out) AS tout
           FROM run WHERE started_at >= ? AND started_at < ? GROUP BY job ORDER BY job""",
        (start, end),
    ).fetchall()
    return {
        "calls": int(sum(d["calls"] or 0 for d in days)),
        "api_equivalent_usd": round(sum(d["est"] or 0 for d in days), 2),
        "days_active": len(days),
        "peak_day": max(((d["d"], int(d["calls"] or 0)) for d in days), key=lambda x: x[1], default=None),
        "runs": [dict(r) for r in runs],
        "billing": "Claude Max 구독 (API 환산 추정, 청구 아님) — ADR-0007",
    }


def run_monthly(
    conn: sqlite3.Connection,
    month: str,
    *,
    now: datetime | None = None,
    reports_dir: Path | None = None,
    digest_dir: Path | None = None,
) -> MonthlyResult:
    now = now or datetime.now(UTC)
    now_iso = now.isoformat(timespec="seconds")
    start, end = month_bounds(month)
    res = MonthlyResult(month=month)
    # 1 theses
    scored = auto_score(conn, today=now.date())
    month_theses = [
        t.as_dict()
        for t in list_theses(conn)
        if t.week.startswith(month[:4]) and (t.horizon_date[:7] == month or t.week[:4] == month[:4])
    ]
    res.theses = {"auto_scored": scored, "calibration": calibration(conn), "in_month": month_theses[:50]}
    # 2 credibility
    res.credibility = update_credibility(conn, start, end, now_iso=now_iso)
    # 4 graph pruning + centrality
    expired = expire_edges(conn, now=now)
    stale = conn.execute(
        "SELECT COUNT(*) FROM entity WHERE status = 'candidate' AND n_stories < 3 AND valid_from IS NOT NULL AND valid_from < ?",
        ((now - timedelta(weeks=4)).date().isoformat(),),
    ).fetchone()[0]
    edges = active_edges(conn, as_of=now.date().isoformat())
    res.graph = {
        "expired_now": expired,
        "stale_candidates": int(stale),
        "counts": graph_counts(conn),
        "hubs": hubs(edges, top=10),
    }
    # 5 cost, quality trend, extraction errors
    res.cost = cost_report(conn, start, end)
    res.quality = [
        dict(r)
        for r in conn.execute(
            "SELECT week, q1_fail, q2_expired, q3_open, q4_merged, q5_errata, status_json FROM quality_run WHERE week >= ? ORDER BY week",
            (f"{month[:4]}-W01",),
        )
    ]
    errs = Counter(
        (r["error"] or "").split(":")[0]
        for r in conn.execute(
            "SELECT error FROM extraction WHERE status = 'failed' AND updated_at >= ? AND updated_at < ?",
            (start, end),
        )
    )
    res.extraction_errors = errs.most_common(5)
    res.pending = [
        "검증기 재학습(§12-3): eval/verify 라벨 200개 전",
        "층별 추출 오류율 e 할인(§6.2.5): Q7 감사 샘플 전 (현재 e=0)",
        "토론 채점(§12-5): 토론 로그 전",
        "프롬프트 제안(§12-7): docs/PROMPT_PROPOSALS.md 는 사람이 월간 md 의 오류 상위를 보고 쓴다",
    ]
    res.macro_background = write_macro_background(conn, month, start, end, res, out_dir=digest_dir)
    res.report = write_retrospective(conn, month, start, end, res, out_dir=reports_dir)
    return res


def write_macro_background(
    conn: sqlite3.Connection,
    month: str,
    start: str,
    end: str,
    res: MonthlyResult,
    *,
    out_dir: Path | None = None,
) -> Path:
    """digests/monthly-macro-YYYY-MM.md — 10 lines for the investment diary (PLAN §11), facts with claim ids only."""
    regimes = conn.execute(
        "SELECT week, regime_json FROM regime_week WHERE week >= ? ORDER BY week", (f"{month[:4]}-W01",)
    ).fetchall()
    regime_lines = []
    for r in regimes:
        rj = json.loads(r["regime_json"] or "{}")
        if (rj.get("as_of") or "")[:7] == month:
            regime_lines.append(f"{r['week']}: {rj.get('line', '-')}")
    top = conn.execute(
        f"""SELECT id, text, label, impact FROM claim WHERE status = 'active' AND first_seen >= ? AND first_seen < ?
            AND label IN ({",".join("?" * len(FACT_LABELS))}) ORDER BY impact DESC, confidence DESC LIMIT 5""",  # noqa: S608
        (start, end, *FACT_LABELS),
    ).fetchall()
    filtered = conn.execute(
        "SELECT label, COUNT(*) n FROM claim WHERE first_seen >= ? AND first_seen < ? AND label IN ('DEBUNKED','RECYCLED','SPAM_SATIRE','DISPUTED') GROUP BY label",
        (start, end),
    ).fetchall()
    n_art = conn.execute(
        "SELECT COUNT(*) FROM article WHERE fetched_at >= ? AND fetched_at < ?", (start, end)
    ).fetchone()[0]
    n_claims = conn.execute(
        "SELECT COUNT(*) FROM claim WHERE first_seen >= ? AND first_seen < ?", (start, end)
    ).fetchone()[0]
    scored = [t for t in res.theses.get("in_month", []) if t.get("outcome") is not None]
    lines = [
        f"# 이달의 거시 배경 {month} — 10줄 (투자일기용, 생성: macroweb monthly)",
        "",
        f"1. **레짐 흐름**: {' → '.join(regime_lines) if regime_lines else '주간 레짐 스냅샷 없음(이 달에 weekly pack 미실행)'}",
        f"2. **검증된 핵심 사실 1**: {_fact(top, 0)}",
        f"3. **검증된 핵심 사실 2**: {_fact(top, 1)}",
        f"4. **검증된 핵심 사실 3**: {_fact(top, 2)}",
        f"5. **논제 채점**: {len(scored)}개 채점, 평균 Brier {res.theses.get('calibration', {}).get('mean_brier')} (n={res.theses.get('calibration', {}).get('n', 0)})",
        f"6. **걸러낸 것**: {', '.join(f'{r["label"]} {r["n"]}' for r in filtered) or '없음'}",
        f"7. **거미줄**: 활성 엣지 {res.graph['counts'].get('edge_candidate', 0) + res.graph['counts'].get('edge_confirmed', 0)} · 이번 달 만료 {res.graph['expired_now']} · 허브 {', '.join(n for n, _ in res.graph['hubs'][:3]) or '-'}",
        f"8. **출처 신뢰도 갱신**: {len(res.credibility)}개 소스 (가장 큰 변화: {_biggest_move(res.credibility)})",
        f"9. **수집·비용**: 기사 {n_art} · claim {n_claims} · 호출 {res.cost['calls']} · API 환산 ${res.cost['api_equivalent_usd']} (구독, 청구 아님)",
        f"10. **다음 달 볼 것**: 미해결 항목 {len(res.pending)}개 — {res.pending[0] if res.pending else '-'}",
        "",
        "> [F] 문장은 claim_id 로 추적 가능 · 매수·매도 지시 없음",
    ]
    d = out_dir or digests_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"monthly-macro-{month}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _fact(rows: list[sqlite3.Row], i: int) -> str:
    if i >= len(rows):
        return "(해당 달 검증 사실 부족)"
    r = rows[i]
    t = (r["text"] or "").replace("\n", " ")
    return f"[F] {t if len(t) <= 110 else t[:107] + '…'} [{r['label']} · {r['id']}]"


def _biggest_move(cred: list[dict[str, Any]]) -> str:
    if not cred:
        return "없음"
    c = max(cred, key=lambda x: abs(x["credibility"] - x["prior"]))
    return f"{c['source']} {c['prior']:.2f}→{c['credibility']:.2f}"


def write_retrospective(
    conn: sqlite3.Connection,
    month: str,
    start: str,
    end: str,
    res: MonthlyResult,
    *,
    out_dir: Path | None = None,
) -> Path:
    d = out_dir or MONTHLY_DIR
    d.mkdir(parents=True, exist_ok=True)
    cal = res.theses.get("calibration", {})
    lines = [
        f"# 월간 회고 {month} (PLAN §12 v1)",
        "",
        "## 1. 논제 채점",
        f"- 자동 채점 {len(res.theses.get('auto_scored', {}).get('scored', []))} · due {len(res.theses.get('auto_scored', {}).get('due', []))} · 자료 없음 {len(res.theses.get('auto_scored', {}).get('no_data', []))}",
        f"- 캘리브레이션: n={cal.get('n', 0)} 평균 Brier {cal.get('mean_brier')} · 구간별 {cal.get('buckets')}",
        "",
        "## 2. 출처 신뢰도 (베이지안, prior 강도 20, 반박 할인 e=0)",
        "| 소스 | 이전 | 갱신 | 확인 | 반박 | claim |",
        "|---|---|---|---|---|---|",
        *[
            f"| {c['source']} | {c['prior']:.2f} | {c['credibility']:.2f} | {c['confirmed']:.0f} | {c['refuted']} | {c['claims']} |"
            for c in res.credibility[:40]
        ],
        "",
        "## 3. 검증기 재학습",
        f"- {res.pending[0]}",
        "",
        "## 4. 그래프 정리",
        f"- 만료 엣지 {res.graph['expired_now']} · 4주 넘은 candidate {res.graph['stale_candidates']} · 상태 {json.dumps(res.graph['counts'], ensure_ascii=False)}",
        f"- 중심성(PageRank) 상위: {', '.join(f'{n} {s:.3f}' for n, s in res.graph['hubs'][:10]) or '-'}",
        "",
        "## 5. 품질 스코어카드 추세",
        *(
            [
                f"- {q['week']}: Q1 실패 {q['q1_fail']} · Q2 만료 {q['q2_expired']} · Q3 미해결 {q['q3_open']} · Q4 병합 {q['q4_merged']} · Q5 정정 {q['q5_errata']}"
                for q in res.quality
            ]
            or ["- 기록 없음"]
        ),
        "",
        "## 6. 비용",
        f"- 호출 {res.cost['calls']} · API 환산 ${res.cost['api_equivalent_usd']} · 활동일 {res.cost['days_active']} · 최다 호출일 {res.cost['peak_day']}",
        f"- run: {json.dumps(res.cost['runs'], ensure_ascii=False)}",
        f"- {res.cost['billing']}",
        "",
        "## 7. 추출 오류 상위 (프롬프트 제안 후보 — docs/PROMPT_PROPOSALS.md 는 사람이 쓴다)",
        *([f"- {k or '(none)'}: {n}" for k, n in res.extraction_errors] or ["- 없음"]),
        "",
        "## 미해결",
        *[f"- {p}" for p in res.pending],
        "",
        f"> 생성 {datetime.now(UTC).isoformat(timespec='minutes')} · 투자일기 배경: digests/monthly-macro-{month}.md",
    ]
    path = d / f"{month}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
