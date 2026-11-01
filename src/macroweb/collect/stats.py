"""Daily collection statistics (Phase 1 DoD "일일 수집 통계 md"): `digests/collect-stats-<KST date>.md`,
regenerated from fetch_log so re-running is idempotent."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from macroweb.paths import digests_dir

KST = ZoneInfo("Asia/Seoul")


def kst_day_bounds(day: str) -> tuple[str, str]:
    start = datetime.fromisoformat(day).replace(tzinfo=KST)
    end = start + timedelta(days=1)
    to_utc = lambda d: d.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")  # noqa: E731
    return to_utc(start), to_utc(end)


def collect_stats(conn: sqlite3.Connection, day: str) -> dict:
    start, end = kst_day_bounds(day)
    rows = conn.execute(
        """SELECT f.source_id, s.tier, COUNT(*) AS fetches, COALESCE(SUM(f.items_new),0) AS items_new,
                  COALESCE(SUM(f.items_seen),0) AS items_seen, COALESCE(SUM(f.market_points),0) AS market_points,
                  SUM(CASE WHEN f.error IS NOT NULL OR f.status >= 400 THEN 1 ELSE 0 END) AS errors,
                  COALESCE(SUM(f.not_modified),0) AS not_modified, MAX(f.fetched_at) AS last_fetch,
                  st.health, st.interval_s, st.last_error
           FROM fetch_log f JOIN source s ON s.id = f.source_id LEFT JOIN source_stats st ON st.source_id = f.source_id
           WHERE f.fetched_at >= ? AND f.fetched_at < ? GROUP BY f.source_id ORDER BY s.tier, f.source_id""",
        (start, end),
    ).fetchall()
    articles = conn.execute(
        "SELECT COUNT(*) AS n FROM article WHERE fetched_at >= ? AND fetched_at < ?", (start, end)
    ).fetchone()["n"]
    bodies = conn.execute(
        "SELECT COUNT(*) AS n FROM article WHERE fetched_at >= ? AND fetched_at < ? AND body_status = 'fetched'",
        (start, end),
    ).fetchone()["n"]
    stories = conn.execute(
        "SELECT COUNT(*) AS n FROM story WHERE first_seen >= ? AND first_seen < ?", (start, end)
    ).fetchone()["n"]
    market = conn.execute("SELECT COUNT(*) AS n FROM market").fetchone()["n"]
    degraded = [
        r["source_id"]
        for r in conn.execute("SELECT source_id FROM source_stats WHERE health = 'degraded'").fetchall()
    ]
    silent = conn.execute(
        """SELECT s.id FROM source s LEFT JOIN source_stats st ON st.source_id = s.id
           WHERE s.enabled = 1 AND (st.last_ok_at IS NULL OR st.last_ok_at < ?)""",
        ((datetime.fromisoformat(end) - timedelta(hours=48)).isoformat(timespec="seconds"),),
    ).fetchall()
    return {
        "day": day,
        "rows": rows,
        "articles": articles,
        "bodies": bodies,
        "stories": stories,
        "market_total": market,
        "degraded": degraded,
        "silent_48h": [r["id"] for r in silent],
    }


def render_stats(stats: dict) -> str:
    rows = stats["rows"]
    lines = [
        f"# 수집 통계 {stats['day']} (KST)",
        "",
        f"- 기사 신규 **{stats['articles']}** · 본문 수집 {stats['bodies']} · Story 신규 {stats['stories']} · market 누적 {stats['market_total']}",
        f"- fetch {sum(r['fetches'] for r in rows)}회 / 소스 {len(rows)}개 · 오류 {sum(r['errors'] or 0 for r in rows)} · 304 {sum(r['not_modified'] for r in rows)}",
        f"- degraded: {', '.join(stats['degraded']) or '없음'} · 48h 침묵(enabled): {', '.join(stats['silent_48h']) or '없음'}",
        "",
        "| source | T | fetch | new | seen | mkt | err | 304 | interval | health | last error |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        interval = f"{int(r['interval_s'] or 0) // 60}m" if r["interval_s"] else "-"
        err = (r["last_error"] or "")[:40]
        lines.append(
            f"| {r['source_id']} | T{r['tier']} | {r['fetches']} | {r['items_new']} | {r['items_seen']} | {r['market_points']} | "
            f"{r['errors'] or 0} | {r['not_modified']} | {interval} | {r['health'] or ''} | {err} |"
        )
    lines.append("")
    lines.append(
        "> 생성: `uv run macroweb stats --date " + stats["day"] + "` (fetch_log 기준, 재실행 시 덮어씀)"
    )
    return "\n".join(lines) + "\n"


def write_collect_stats(conn: sqlite3.Connection, day: str) -> Path:
    out_dir = digests_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"collect-stats-{day}.md"
    path.write_text(render_stats(collect_stats(conn, day)), encoding="utf-8")
    return path
