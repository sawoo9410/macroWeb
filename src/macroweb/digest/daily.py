"""Daily 10-line digest (PLAN §14 Phase 2 DoD, template digests/_template-daily.md). Every line is filled from the
DB or config — nothing is written that the pipeline did not measure. Lines whose engine does not exist yet
(regime detector, cross-asset consistency, T0 diff — Phase 3) say so instead of guessing."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from macroweb.analysis.consistency import cross_asset_check
from macroweb.analysis.regime import compute_regime
from macroweb.collect import store
from macroweb.config import CalendarConfig, load_models, load_yaml
from macroweb.paths import CONFIG_DIR, ROOT, digests_dir

KST = ZoneInfo("Asia/Seoul")
TEMPLATE = ROOT / "digests" / "_template-daily.md"
FACT_LABELS = ("VERIFIED", "CORROBORATED")
FILTERED_LABELS = ("DEBUNKED", "RECYCLED", "SPAM_SATIRE")
SNAPSHOT_KEYS = (
    ("UST:10Y", "미 10Y", "%"),
    ("UST:2Y", "미 2Y", "%"),
    ("NAVER:.DXY", "DXY", ""),
    ("NAVER:.VIX", "VIX", ""),
    ("NAVER:KOSPI", "KOSPI", ""),
    ("ECB:USD_KRW_CROSS", "USD/KRW(ECB)", ""),
    ("KRAKEN:XBTUSD", "BTC", "$"),
)
CALENDAR_HORIZON_DAYS = 14


def kst_day_bounds(day: str) -> tuple[str, str]:
    """[start, end) of a KST calendar day as UTC ISO strings (DB timestamps are UTC ISO)."""
    d = date.fromisoformat(day)
    start = datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(UTC)
    return start.isoformat(timespec="seconds"), (start + timedelta(days=1)).isoformat(timespec="seconds")


@dataclass
class DigestData:
    day: str
    values: dict[str, str] = field(default_factory=dict)
    top_claims: list[sqlite3.Row] = field(default_factory=list)


def _short(text: str | None, n: int = 110) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _fmt(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "$":
        return f"${value:,.0f}"
    return f"{value:,.2f}" if value < 1000 else f"{value:,.0f}"


def market_snapshot(conn: sqlite3.Connection) -> str:
    latest = {r["key"]: r for r in store.market_latest(conn)}
    parts = []
    for key, name, unit in SNAPSHOT_KEYS:
        r = latest.get(key)
        if r is not None:
            parts.append(f"{name} {_fmt(float(r['value']), unit)} ({str(r['date'])[5:]})")
    return " · ".join(parts) if parts else "market 테이블 비어 있음"


def build_digest(conn: sqlite3.Connection, day: str) -> DigestData:
    start, end = kst_day_bounds(day)
    v: dict[str, str] = {"date": day}
    # 1 regime (Phase 3) → market snapshot with dates, nothing interpreted
    regime = compute_regime(conn, as_of=day)
    v["regime_line"] = f"{regime.line()} · 스냅샷: {market_snapshot(conn)}"
    # 2 T0 primary documents seen today
    t0 = conn.execute(
        """SELECT s.id, s.title_rep, a.source_id FROM story s
           JOIN article a ON a.id = COALESCE(s.rep_article_id, (SELECT article_id FROM story_article WHERE story_id = s.id LIMIT 1))
           JOIN source src ON src.id = a.source_id
           WHERE src.tier = 0 AND s.first_seen >= ? AND s.first_seen < ? ORDER BY s.first_seen DESC""",
        (start, end),
    ).fetchall()
    v["n_t0"] = str(len(t0))
    v["n_diff"] = "0 (T0 diff 는 Phase 2 후반)"
    t0_read = conn.execute(
        """SELECT s.title_rep, src.id AS source_id, COUNT(c.id) AS n FROM claim c
           JOIN story s ON s.id = c.story_id JOIN article a ON a.id = s.rep_article_id
           JOIN source src ON src.id = a.source_id
           WHERE src.tier = 0 AND c.first_seen >= ? AND c.first_seen < ?
           GROUP BY s.id ORDER BY n DESC LIMIT 3""",
        (start, end),
    ).fetchall()
    if t0_read:  # documents the extractor actually read today, with how many claims each gave
        v["t0_docs"] = "; ".join(
            f"{_short(r['title_rep'], 60)} [{r['source_id']}, claim {r['n']}]" for r in t0_read
        )
    elif t0:
        v["t0_docs"] = (
            "; ".join(f"{_short(r['title_rep'], 60)} [{r['source_id']}]" for r in t0[:3]) + " (아직 추출 전)"
        )
    else:
        v["t0_docs"] = "오늘 새 1차 문서 없음"
    # 3–5 high-impact fact claims extracted today (claim.first_seen = extraction time, not the story's age)
    claims = conn.execute(
        f"""SELECT c.id, c.text, c.label, c.impact, c.confidence FROM claim c
            WHERE c.status = 'active' AND c.first_seen >= ? AND c.first_seen < ?
              AND c.label IN ({",".join("?" * len(FACT_LABELS))})
            ORDER BY c.impact DESC, c.confidence DESC, c.first_seen DESC LIMIT 3""",  # noqa: S608 - placeholders only
        (start, end, *FACT_LABELS),
    ).fetchall()
    for i in range(1, 4):
        if i <= len(claims):
            c = claims[i - 1]
            v[f"claim_{i}"] = f"[F] {_short(c['text'])}"
            v[f"claim_{i}_label"] = (
                f"{c['label']} conf {float(c['confidence'] or 0):.2f} impact {float(c['impact'] or 0):.2f}"
            )
            v[f"claim_{i}_id"] = c["id"]
        else:
            v[f"claim_{i}"] = "(오늘 검증 사실 claim 부족)"
            v[f"claim_{i}_label"] = "-"
            v[f"claim_{i}_id"] = "-"
    # 6 cross-asset consistency (Phase 3)
    v["market_consistency"] = cross_asset_check(conn, _digest_shocks(day), as_of=day).line()
    # 7 review queue created today
    n_review = conn.execute(
        "SELECT COUNT(*) FROM review_queue WHERE created_at >= ? AND created_at < ?", (start, end)
    ).fetchone()[0]
    v["n_review"] = str(n_review)
    # 8 filtered
    filtered = conn.execute(
        f"""SELECT c.label, COUNT(*) AS n FROM claim c
            WHERE c.first_seen >= ? AND c.first_seen < ? AND c.label IN ({",".join("?" * len(FILTERED_LABELS))})
            GROUP BY c.label""",  # noqa: S608 - placeholders only
        (start, end, *FILTERED_LABELS),
    ).fetchall()
    v["n_filtered"] = str(sum(int(r["n"]) for r in filtered))
    v["filtered"] = ", ".join(f"{r['label']} {r['n']}" for r in filtered) or "없음"
    # 9 collection health & cost
    n_articles = conn.execute(
        "SELECT COUNT(*) FROM article WHERE fetched_at >= ? AND fetched_at < ?", (start, end)
    ).fetchone()[0]
    n_stories = conn.execute(
        "SELECT COUNT(*) FROM story WHERE first_seen >= ? AND first_seen < ?", (start, end)
    ).fetchone()[0]
    degraded = [
        r["source_id"]
        for r in conn.execute(
            "SELECT source_id FROM source_stats WHERE health = 'degraded' ORDER BY source_id"
        )
    ]
    cost_today = float(
        conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_batch WHERE submitted_at >= ? AND submitted_at < ?",
            (start, end),
        ).fetchone()[0]
    )
    month_start = kst_day_bounds(day[:7] + "-01")[0]
    cost_month = float(
        conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_batch WHERE submitted_at >= ?", (month_start,)
        ).fetchone()[0]
    )
    cap = _monthly_cap_usd()
    v["n_articles"] = str(n_articles)
    v["n_stories"] = str(n_stories)
    v["degraded"] = ", ".join(degraded) if degraded else "없음"
    v["cost_today"] = f"{cost_today:.2f} (API 환산, 구독이라 청구 아님)"
    v["cost_pct"] = f"{(100 * cost_month / cap) if cap else 0:.0f}"
    # 10 next calendar events
    v["tomorrow"] = upcoming_events(day)
    return DigestData(day=day, values=v, top_claims=list(claims))


def _digest_shocks(day: str) -> list[tuple[str, int]]:
    """Calendar events within 14 days that exist as graph nodes, shocked +1 (the digest's cross-asset line)."""
    cal = CalendarConfig.model_validate(load_yaml(CONFIG_DIR / "calendar.yaml"))
    d0 = date.fromisoformat(day)
    out = []
    for ev in cal.events:
        try:
            d = date.fromisoformat(ev.date)
        except ValueError:
            continue
        if d0 <= d <= d0 + timedelta(days=14):
            out.append((ev.id, 1))
    return out[:3]


def _monthly_cap_usd() -> float:
    return float(load_models().budget.monthly_cap_usd)


def upcoming_events(day: str, horizon_days: int = CALENDAR_HORIZON_DAYS) -> str:
    cal = CalendarConfig.model_validate(load_yaml(CONFIG_DIR / "calendar.yaml"))
    d0 = date.fromisoformat(day)
    out = []
    for ev in cal.events:
        try:
            d = date.fromisoformat(ev.date)
        except ValueError:
            continue  # "2026-11-TBD" style placeholders stay out until confirmed
        if d0 <= d <= d0 + timedelta(days=horizon_days):
            flag = "" if getattr(ev, "status", "confirmed") == "confirmed" else " (미확정)"
            watch = getattr(ev, "watch", None)
            out.append(f"{ev.date} {ev.name}{flag}" + (f" — {watch}" if watch else ""))
    return "; ".join(out[:4]) if out else f"캘린더에 {horizon_days}일 내 이벤트 없음"


def render_digest(data: DigestData) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    text = template
    for k, val in data.values.items():
        text = text.replace("{{" + k + "}}", val)
    return text


def write_digest(conn: sqlite3.Connection, day: str) -> Path:
    data = build_digest(conn, day)
    out_dir = digests_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.md"
    path.write_text(render_digest(data), encoding="utf-8")
    return path


def digest_json(data: DigestData) -> str:
    return json.dumps(data.values, ensure_ascii=False, indent=1)
