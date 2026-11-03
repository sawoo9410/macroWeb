"""Weekly data-quality review v1 (PLAN §10.5, Phase 3 DoD): Q1 evidence integrity, Q2 expiry/supersession,
Q4 duplicates & source flood, Q6 coverage. Deterministic, reversible auto-fixes only (status changes, never
deletes). Q3/Q5/Q7 are Phase 6 and reported as ⚪. Writes reports/quality/<week>.md and a quality_run row."""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from macroweb.config import QualityConfig, load_quality
from macroweb.graph.analysis import week_bounds
from macroweb.graph.store import expire_edges, resolve_entities
from macroweb.paths import ROOT, raw_dir

REPORTS_DIR = ROOT / "reports" / "quality"
LIGHTS = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "⚪"}
CURRENT_STATE_TYPES = ("numeric", "event")


@dataclass
class QualityResult:
    week: str
    q1: dict[str, Any] = field(default_factory=dict)
    q2: dict[str, Any] = field(default_factory=dict)
    q4: dict[str, Any] = field(default_factory=dict)
    q6: dict[str, Any] = field(default_factory=dict)
    lights: dict[str, str] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    report: Path | None = None

    def scoreline(self) -> str:
        parts = []
        for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"):
            light = self.lights.get(q, "na")
            extra = ""
            if q == "Q2":
                extra = f"({self.q2.get('expired_claims', 0) + self.q2.get('superseded', 0) + self.q2.get('expired_edges', 0)})"
            if q == "Q4" and self.q4.get("flood"):
                extra = f"({self.q4['flood'][0]})"
            parts.append(f"{q}{LIGHTS[light]}{extra}")
        return "데이터 품질: " + " ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "q1": self.q1,
            "q2": self.q2,
            "q4": self.q4,
            "q6": self.q6,
            "lights": self.lights,
            "actions": self.actions,
        }


def run_quality(
    conn: sqlite3.Connection,
    week: str,
    *,
    now: datetime | None = None,
    cfg: QualityConfig | None = None,
    apply: bool = True,
    reports_dir: Path | None = None,
) -> QualityResult:
    cfg = cfg or load_quality()
    now = now or datetime.now(UTC)
    res = QualityResult(week=week)
    start, end = week_bounds(week)
    res.q1 = _q1_evidence(conn, apply=apply, actions=res.actions)
    res.q2 = _q2_expiry(conn, now=now, apply=apply, actions=res.actions)
    res.q4 = _q4_duplicates(conn, start=start, end=end, now=now, cfg=cfg, apply=apply, actions=res.actions)
    res.q6 = _q6_coverage(conn, start=start, end=end, cfg=cfg)
    res.lights = {
        "Q1": "red" if res.q1["fail"] else "green",
        "Q2": "green",
        "Q3": "na",
        "Q4": "yellow" if (res.q4.get("flood") or res.q4.get("stale_candidates")) else "green",
        "Q5": "na",
        "Q6": "yellow"
        if (res.q6.get("drops") or res.q6.get("silent") or res.q6.get("t0_share_low"))
        else "green",
        "Q7": "na",
    }
    conn.execute(
        """INSERT INTO quality_run(week, q1_fail, q2_expired, q2_superseded, q3_open, q4_merged, q4_flood_source, q5_errata, q6_json, q7_json, status_json)
           VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, ?, NULL, ?)
           ON CONFLICT(week) DO UPDATE SET q1_fail = excluded.q1_fail, q2_expired = excluded.q2_expired, q2_superseded = excluded.q2_superseded,
             q4_merged = excluded.q4_merged, q4_flood_source = excluded.q4_flood_source, q6_json = excluded.q6_json, status_json = excluded.status_json""",
        (
            week,
            res.q1["fail"],
            res.q2["expired_claims"] + res.q2["expired_edges"],
            res.q2["superseded"],
            len(res.q4.get("merged", [])),
            (res.q4.get("flood") or [None])[0],
            json.dumps(res.q6, ensure_ascii=False),
            json.dumps(
                {"lights": res.lights, "actions": res.actions, "ran_at": now.isoformat(timespec="seconds")},
                ensure_ascii=False,
            ),
        ),
    )
    conn.commit()
    res.report = write_report(res, conn, reports_dir=reports_dir)
    return res


# --- Q1 ----------------------------------------------------------------------------------------------------
def _q1_evidence(conn: sqlite3.Connection, *, apply: bool, actions: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "fail": 0,
        "quarantined_edges": 0,
        "quarantined_claims": 0,
        "seed_pending": 0,
        "missing_raw": 0,
    }
    for r in conn.execute(
        "SELECT id, origin, evidence_ids FROM relation WHERE status IN ('candidate','confirmed') AND (evidence_ids IS NULL OR evidence_ids = '[]')"
    ).fetchall():
        if r["origin"] in ("seed", "computed"):
            out["seed_pending"] += 1  # human-reviewed base / computed stats: allowed without claims, reported
            continue
        out["fail"] += 1
        if apply:
            conn.execute("UPDATE relation SET status = 'quarantined' WHERE id = ?", (r["id"],))
            out["quarantined_edges"] += 1
    orphan = conn.execute(
        """SELECT c.id FROM claim c WHERE c.status = 'active'
           AND NOT EXISTS (SELECT 1 FROM evidence e JOIN article a ON a.id = e.article_id WHERE e.claim_id = c.id)"""
    ).fetchall()
    out["fail"] += len(orphan)
    if apply and orphan:
        conn.executemany("UPDATE claim SET status = 'quarantined' WHERE id = ?", [(r["id"],) for r in orphan])
        out["quarantined_claims"] = len(orphan)
    base = raw_dir()
    for r in conn.execute(
        """SELECT DISTINCT a.raw_path FROM evidence e JOIN article a ON a.id = e.article_id JOIN claim c ON c.id = e.claim_id
           WHERE c.status = 'active' AND a.raw_path IS NOT NULL"""
    ):
        p = Path(r["raw_path"])
        if not p.is_absolute():
            p = base / p
        if not p.exists():
            out["missing_raw"] += 1
    out["fail"] += out["missing_raw"]
    if out["quarantined_edges"] or out["quarantined_claims"]:
        actions.append(
            f"Q1: quarantined {out['quarantined_edges']} edges, {out['quarantined_claims']} claims without evidence"
        )
    conn.commit()
    return out


# --- Q2 ----------------------------------------------------------------------------------------------------
def _q2_expiry(conn: sqlite3.Connection, *, now: datetime, apply: bool, actions: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"expired_claims": 0, "superseded": 0, "expired_edges": 0}
    today = now.date().isoformat()
    forecasts = conn.execute(
        "SELECT id, time_ref FROM claim WHERE status = 'active' AND type = 'forecast' AND time_ref IS NOT NULL"
    ).fetchall()
    stale = [
        r["id"]
        for r in forecasts
        if _period_end(str(r["time_ref"])) is not None and str(_period_end(str(r["time_ref"]))) < today
    ]
    out["expired_claims"] = len(stale)
    if apply and stale:
        conn.executemany("UPDATE claim SET status = 'expired' WHERE id = ?", [(cid,) for cid in stale])
    rows = conn.execute(
        f"""SELECT id, subject_eid, predicate, first_seen, value FROM claim
            WHERE status = 'active' AND subject_eid IS NOT NULL AND predicate IS NOT NULL AND type IN ({",".join("?" * len(CURRENT_STATE_TYPES))})
            ORDER BY subject_eid, predicate, first_seen DESC""",  # noqa: S608 - placeholders only
        CURRENT_STATE_TYPES,
    ).fetchall()
    newest: dict[tuple[str, str], sqlite3.Row] = {}
    superseded: list[tuple[str, str]] = []
    for r in rows:
        key = (r["subject_eid"], (r["predicate"] or "").strip().lower())
        if key not in newest:
            newest[key] = r
        elif (
            r["first_seen"]
            and newest[key]["first_seen"]
            and r["first_seen"] < newest[key]["first_seen"]
            and r["value"] != newest[key]["value"]
        ):
            superseded.append((newest[key]["id"], r["id"]))
    out["superseded"] = len(superseded)
    if apply and superseded:
        conn.executemany("UPDATE claim SET status = 'superseded', superseded_by = ? WHERE id = ?", superseded)
    out["expired_edges"] = expire_edges(conn, now=now) if apply else 0
    if any(out.values()):
        actions.append(
            f"Q2: expired {out['expired_claims']} forecasts, superseded {out['superseded']} claims, expired {out['expired_edges']} edges"
        )
    conn.commit()
    return out


def _period_end(time_ref: str) -> str | None:
    t = time_ref.strip()
    if len(t) == 4 and t.isdigit():
        return f"{t}-12-31"
    if len(t) == 7 and t[4] == "-":
        return f"{t}-31"
    if len(t) >= 10 and t[4] == "-" and t[7] == "-":
        return t[:10]
    return None


# --- Q4 ----------------------------------------------------------------------------------------------------
def _q4_duplicates(
    conn: sqlite3.Connection,
    *,
    start: str,
    end: str,
    now: datetime,
    cfg: QualityConfig,
    apply: bool,
    actions: list[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {"merged": [], "stale_candidates": [], "flood": None, "edge_share_by_source": {}}
    if apply:
        rep = resolve_entities(conn, now=now)
        out["merged"] = [f"{a}→{b}" for a, b in rep.merged]
        if rep.merged:
            actions.append(f"Q4: merged {len(rep.merged)} alias duplicates ({', '.join(out['merged'][:5])})")
    max_weeks = int((cfg.checks["Q4"].alert or {}).get("candidate_max_weeks", 4))
    cutoff = (now - timedelta(weeks=max_weeks)).date().isoformat()
    stale = conn.execute(
        "SELECT id FROM entity WHERE status = 'candidate' AND n_stories < 3 AND valid_from IS NOT NULL AND valid_from < ?",
        (cutoff,),
    ).fetchall()
    out["stale_candidates"] = [r["id"] for r in stale]
    if apply and stale:
        conn.executemany("UPDATE entity SET status = 'inactive' WHERE id = ?", [(r["id"],) for r in stale])
        actions.append(f"Q4: deactivated {len(stale)} candidates older than {max_weeks} weeks")
    share_limit = float((cfg.checks["Q4"].alert or {}).get("source_flood_share", 0.30))
    counts: Counter[str] = Counter()
    for e in conn.execute(
        "SELECT evidence_ids FROM relation WHERE valid_from >= ? AND valid_from < ? AND origin = 'extracted'",
        (start, end),
    ):
        ev = json.loads(e["evidence_ids"] or "[]")
        if not ev:
            continue
        row = conn.execute("SELECT signals_json FROM claim WHERE id = ?", (ev[0],)).fetchone()
        src = (json.loads(row["signals_json"] or "{}").get("source_id") if row else None) or "unknown"
        counts[src] += 1
    total = sum(counts.values())
    if total:
        out["edge_share_by_source"] = {k: round(v / total, 3) for k, v in counts.most_common(8)}
        top, n = counts.most_common(1)[0]
        if n / total >= share_limit and total >= 10:
            out["flood"] = [top, round(n / total, 3)]
            if apply:
                conn.execute(
                    "INSERT INTO review_queue(kind, reason, payload_json, created_at) VALUES ('source_flood', ?, ?, ?)",
                    (
                        f"{top} made {n}/{total} new edges this week",
                        json.dumps(out["edge_share_by_source"]),
                        now.isoformat(timespec="seconds"),
                    ),
                )
    conn.commit()
    return out


# --- Q6 ----------------------------------------------------------------------------------------------------
def _q6_coverage(conn: sqlite3.Connection, *, start: str, end: str, cfg: QualityConfig) -> dict[str, Any]:
    alert = cfg.checks["Q6"].alert or {}
    drop_limit = float(alert.get("volume_drop_vs_median", -0.5))
    t0_floor = float(alert.get("t0_share_yellow_below", 0.2))
    out: dict[str, Any] = {
        "drops": [],
        "silent": [],
        "t0_share": None,
        "t0_share_low": False,
        "history_weeks": 0,
        "this_week": {},
    }
    this_week = {
        r["source_id"]: int(r["n"])
        for r in conn.execute(
            "SELECT source_id, COUNT(*) n FROM article WHERE fetched_at >= ? AND fetched_at < ? GROUP BY source_id",
            (start, end),
        )
    }
    out["this_week"] = dict(sorted(this_week.items(), key=lambda kv: -kv[1])[:12])
    start_dt = datetime.fromisoformat(start)
    history: dict[str, list[int]] = defaultdict(list)
    weeks_with_data = 0
    for k in range(1, 5):
        s = (start_dt - timedelta(weeks=k)).isoformat(timespec="seconds")
        e = (start_dt - timedelta(weeks=k - 1)).isoformat(timespec="seconds")
        rows = conn.execute(
            "SELECT source_id, COUNT(*) n FROM article WHERE fetched_at >= ? AND fetched_at < ? GROUP BY source_id",
            (s, e),
        ).fetchall()
        if rows:
            weeks_with_data += 1
        wk = {r["source_id"]: int(r["n"]) for r in rows}
        for sid in set(wk) | set(this_week):
            history[sid].append(wk.get(sid, 0))
    out["history_weeks"] = weeks_with_data
    if weeks_with_data >= 2:
        for sid, hist in history.items():
            med = statistics.median(hist) if hist else 0
            if med >= 5 and (this_week.get(sid, 0) - med) / med <= drop_limit:
                out["drops"].append({"source": sid, "this_week": this_week.get(sid, 0), "median_4w": med})
    else:
        out["note"] = f"coverage baseline needs ≥ 2 previous weeks (have {weeks_with_data})"
    silent = conn.execute(
        """SELECT s.id, st.last_ok_at, st.health FROM source s JOIN source_stats st ON st.source_id = s.id
           WHERE s.enabled = 1 AND (st.health = 'degraded' OR st.last_ok_at IS NULL OR st.last_ok_at < ?)""",
        ((datetime.fromisoformat(end) - timedelta(hours=48)).isoformat(timespec="seconds"),),
    ).fetchall()
    out["silent"] = [
        {"source": r["id"], "last_ok_at": r["last_ok_at"], "health": r["health"]} for r in silent
    ]
    top = conn.execute(
        """SELECT c.stratum FROM claim c WHERE c.status = 'active' AND c.first_seen >= ? AND c.first_seen < ? AND c.impact >= 0.7""",
        (start, end),
    ).fetchall()
    if top:
        t0 = sum(1 for r in top if (r["stratum"] or "").startswith("S-T0"))
        out["t0_share"] = round(t0 / len(top), 3)
        out["t0_share_low"] = out["t0_share"] < t0_floor
    return out


# --- report ------------------------------------------------------------------------------------------------
def write_report(res: QualityResult, conn: sqlite3.Connection, *, reports_dir: Path | None = None) -> Path:
    d = reports_dir or REPORTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    prev = conn.execute(
        "SELECT week, q1_fail, q2_expired, q4_merged FROM quality_run WHERE week < ? ORDER BY week DESC LIMIT 1",
        (res.week,),
    ).fetchone()
    lines = [
        f"# 주간 데이터 품질 검토 {res.week} (v1: Q1·Q2·Q4·Q6 · Q3/Q5/Q7 은 Phase 6)",
        "",
        f"**{res.scoreline()}**",
        "",
        "| 검사 | 신호등 | 결과 |",
        "|---|---|---|",
        f"| Q1 근거 무결성 | {LIGHTS[res.lights['Q1']]} | 실패 {res.q1['fail']} (격리 엣지 {res.q1['quarantined_edges']}, 격리 claim {res.q1['quarantined_claims']}, raw 누락 {res.q1['missing_raw']}) · 시드/통계 엣지 evidence 대기 {res.q1['seed_pending']} |",
        f"| Q2 시효 | {LIGHTS[res.lights['Q2']]} | 만기 forecast {res.q2['expired_claims']} · superseded {res.q2['superseded']} · 만료 엣지 {res.q2['expired_edges']} |",
        "| Q3 모순 | ⚪ | Phase 6 |",
        f"| Q4 중복·오염 | {LIGHTS[res.lights['Q4']]} | 별칭 병합 {len(res.q4.get('merged', []))} · 오래된 candidate 비활성 {len(res.q4.get('stale_candidates', []))} · 소스 쏠림 {res.q4.get('flood') or '없음'} |",
        "| Q5 소급 정정 | ⚪ | Phase 6 |",
        f"| Q6 커버리지 | {LIGHTS[res.lights['Q6']]} | 급감 소스 {len(res.q6.get('drops', []))} · 침묵 소스 {len(res.q6.get('silent', []))} · 상위 claim T0 비율 {res.q6.get('t0_share')} · 기준 주 {res.q6.get('history_weeks')} {('— ' + res.q6['note']) if res.q6.get('note') else ''} |",
        "| Q7 추출 감사 | ⚪ | Phase 6 |",
        "",
        "## 자동 처리 로그",
        *([f"- {a}" for a in res.actions] or ["- 없음"]),
        "",
        "## 세부",
        f"- Q4 이번 주 신규 엣지 소스 분포: {json.dumps(res.q4.get('edge_share_by_source'), ensure_ascii=False)}",
        f"- Q6 이번 주 소스별 기사 수(상위): {json.dumps(res.q6.get('this_week'), ensure_ascii=False)}",
        f"- Q6 침묵 소스: {json.dumps(res.q6.get('silent'), ensure_ascii=False)}",
        "",
        "## 지난주 대비",
        (
            f"- {prev['week']}: Q1 실패 {prev['q1_fail']} · Q2 만료 {prev['q2_expired']} · Q4 병합 {prev['q4_merged']}"
            if prev
            else "- 이전 기록 없음"
        ),
        "",
        "> 게이트(PLAN §10.5): Q1 실패분은 데이터팩 제외 · Q6 빨강 테마는 새 논제 금지 · 빨강 2개 이상이면 리포트 상단 경보.",
    ]
    path = d / f"{res.week}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
