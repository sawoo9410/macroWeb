"""SQLite writes/reads for the collection pipeline: source sync, due sources, articles, market points,
fetch log, story grouping. Everything is idempotent (INSERT OR IGNORE / OR REPLACE keyed by canonical URL,
(date, key), or source id)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from macroweb.collect.dedupe import article_id, canonical_url, hamming_hex, simhash_hex
from macroweb.collect.models import FetchResponse, Item, MarketPoint
from macroweb.collect.scheduler import compute_interval, next_due
from macroweb.config import Source

DEGRADED_AFTER = 3  # consecutive failures (PLAN §4.3)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sync_sources(conn: sqlite3.Connection, sources: list[Source]) -> int:
    for s in sources:
        conn.execute(
            """INSERT INTO source(id, name, tier, kind, url, lang, country, topics, paywall, enabled, parser, rate_limit_s, parent_org, stratum, fetch_body)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, tier=excluded.tier, kind=excluded.kind, url=excluded.url,
                 lang=excluded.lang, country=excluded.country, topics=excluded.topics, paywall=excluded.paywall,
                 enabled=excluded.enabled, parser=excluded.parser, rate_limit_s=excluded.rate_limit_s,
                 parent_org=excluded.parent_org, stratum=excluded.stratum, fetch_body=excluded.fetch_body""",
            (
                s.id,
                s.name,
                s.tier,
                s.kind,
                s.url,
                s.lang,
                s.country,
                json.dumps(s.topics, ensure_ascii=False),
                int(s.paywall),
                int(s.enabled),
                s.parser,
                s.rate_limit_s,
                s.parent_org,
                s.stratum,
                int(s.fetch_body),
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO source_stats(source_id, credibility, health, updated_at) VALUES (?, ?, 'ok', ?)",
            (s.id, s.credibility_prior, _now_iso()),
        )
    conn.commit()
    return len(sources)


def source_stats(conn: sqlite3.Connection, source_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM source_stats WHERE source_id = ?", (source_id,)).fetchone()


def all_stats(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["source_id"]: r for r in conn.execute("SELECT * FROM source_stats").fetchall()}


def record_fetch(
    conn: sqlite3.Connection,
    src: Source,
    *,
    resp: FetchResponse | None,
    raw_path: str | None,
    items_seen: int,
    items_new: int,
    market_points: int,
    feed_window_s: int | None,
    error: str | None,
    run_id: str | None,
    event_active: bool,
    now: datetime,
) -> dict[str, Any]:
    stats = source_stats(conn, src.id)
    prev_fail = int(stats["consecutive_failures"] or 0) if stats else 0
    failed = error is not None or (resp is not None and resp.status >= 400)
    consecutive = prev_fail + 1 if failed else 0
    health = "degraded" if consecutive >= DEGRADED_AFTER else "ok"
    prev_window = int(stats["feed_window_s"]) if stats and stats["feed_window_s"] else None
    window = feed_window_s or prev_window
    interval = compute_interval(window, src.kind, src.tier, fixed=src.interval_s)
    if failed:
        interval = min(interval * (2 ** min(consecutive, 4)), 24 * 3600)  # back off, max 1 day
    due = next_due(now, interval, src.tier, event_active)
    conn.execute(
        """UPDATE source_stats SET last_fetch_at=?, next_due_at=?, interval_s=?, feed_window_s=?, etag=?, last_modified=?,
             last_status=?, last_error=?, consecutive_failures=?, health=?, last_ok_at=COALESCE(?, last_ok_at),
             n_fetches=COALESCE(n_fetches,0)+1, n_items_total=COALESCE(n_items_total,0)+?, updated_at=? WHERE source_id=?""",
        (
            now.isoformat(timespec="seconds"),
            due.isoformat(timespec="seconds"),
            interval,
            window,
            (resp.etag if resp and not resp.not_modified else (stats["etag"] if stats else None)),
            (
                resp.last_modified
                if resp and not resp.not_modified
                else (stats["last_modified"] if stats else None)
            ),
            resp.status if resp else None,
            (error or "")[:300] or None,
            consecutive,
            health,
            None if failed else now.isoformat(timespec="seconds"),
            items_new,
            _now_iso(),
            src.id,
        ),
    )
    conn.execute(
        """INSERT INTO fetch_log(source_id, fetched_at, status, not_modified, items_seen, items_new, market_points, bytes,
             elapsed_ms, error, raw_path, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            src.id,
            now.isoformat(timespec="seconds"),
            resp.status if resp else None,
            int(bool(resp and resp.not_modified)),
            items_seen,
            items_new,
            market_points,
            len(resp.content) if resp else 0,
            resp.elapsed_ms if resp else None,
            (error or "")[:300] or None,
            raw_path,
            run_id,
        ),
    )
    conn.commit()
    return {
        "interval_s": interval,
        "next_due_at": due.isoformat(timespec="seconds"),
        "health": health,
        "consecutive_failures": consecutive,
    }


def upsert_article(
    conn: sqlite3.Connection,
    src: Source,
    item: Item,
    *,
    raw_path: str | None,
    sha256: str | None,
    fetched_at: datetime,
) -> tuple[str, bool]:
    canon = canonical_url(item.url)
    aid = article_id(canon)
    exists = conn.execute("SELECT 1 FROM article WHERE canonical_url = ?", (canon,)).fetchone()
    if exists:
        return aid, False
    published = item.published_at.astimezone(UTC).isoformat(timespec="seconds") if item.published_at else None
    conn.execute(
        """INSERT OR IGNORE INTO article(id, url, canonical_url, source_id, title, author, published_at, fetched_at, lang, text,
             summary, raw_path, sha256, paywalled, status, title_simhash, body_status, extra_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?)""",
        (
            aid,
            item.url,
            canon,
            src.id,
            item.title,
            item.author,
            published,
            fetched_at.isoformat(timespec="seconds"),
            item.lang or src.lang,
            item.text,
            item.summary,
            raw_path,
            sha256,
            int(src.paywall),
            simhash_hex(item.title),
            "fetched" if item.text else ("paywalled" if src.paywall else "none"),
            json.dumps(item.extra, ensure_ascii=False) if item.extra else None,
        ),
    )
    return aid, True


def insert_market(conn: sqlite3.Connection, points: list[MarketPoint]) -> int:
    n = 0
    for p in points:
        conn.execute(
            "INSERT OR REPLACE INTO market(date, key, value, source) VALUES (?, ?, ?, ?)",
            (p.date, p.key, p.value, p.source),
        )
        n += 1
    return n


def market_latest(conn: sqlite3.Connection, like: str | None = None) -> list[sqlite3.Row]:
    """Newest point per key (optionally key LIKE pattern, e.g. 'UST:%'), with the number of stored days."""
    where = "WHERE key LIKE ?" if like else ""
    args: tuple[str, ...] = (like,) if like else ()
    return conn.execute(
        f"""SELECT m.key, m.date, m.value, m.source, c.n_days, c.first_date
            FROM market m
            JOIN (SELECT key, MAX(date) AS max_date, COUNT(*) AS n_days, MIN(date) AS first_date
                  FROM market {where} GROUP BY key) c
              ON c.key = m.key AND c.max_date = m.date
            ORDER BY m.key""",
        args,
    ).fetchall()


def market_series(conn: sqlite3.Connection, key: str, limit: int = 30) -> list[sqlite3.Row]:
    """Most recent `limit` points of one key, oldest first."""
    rows = conn.execute(
        "SELECT date, value, source FROM market WHERE key = ? ORDER BY date DESC LIMIT ?", (key, limit)
    ).fetchall()
    return list(reversed(rows))


# --- story grouping (SimHash stage) -------------------------------------------------------------------
def group_into_stories(
    conn: sqlite3.Connection, *, max_hamming: int = 3, window_hours: int = 72
) -> dict[str, int]:
    since = (datetime.now(UTC) - timedelta(hours=window_hours)).isoformat(timespec="seconds")
    recent = conn.execute(
        """SELECT s.id, s.title_simhash FROM story s WHERE s.last_seen >= ? AND s.title_simhash IS NOT NULL""",
        (since,),
    ).fetchall()
    stories = [(r["id"], r["title_simhash"]) for r in recent]
    pending = conn.execute(
        """SELECT a.id, a.title, a.title_simhash, a.source_id, a.fetched_at, a.published_at
           FROM article a LEFT JOIN story_article sa ON sa.article_id = a.id
           WHERE sa.article_id IS NULL AND a.title_simhash IS NOT NULL ORDER BY a.fetched_at"""
    ).fetchall()
    created = attached = syndicated = 0
    for a in pending:
        match = None
        for sid, sh in stories:
            if hamming_hex(a["title_simhash"], sh) <= max_hamming:
                match = sid
                break
        ts = a["published_at"] or a["fetched_at"]
        if match is None:
            sid = f"st-{a['id']}"
            conn.execute(
                "INSERT INTO story(id, first_seen, last_seen, title_rep, n_articles, n_independent, title_simhash) VALUES (?, ?, ?, ?, 1, 1, ?)",
                (sid, ts, ts, a["title"], a["title_simhash"]),
            )
            conn.execute(
                "INSERT OR IGNORE INTO story_article(story_id, article_id, is_syndicated) VALUES (?, ?, 0)",
                (sid, a["id"]),
            )
            stories.append((sid, a["title_simhash"]))
            created += 1
        else:
            # same parent org or near-identical title from another outlet = syndicated copy, not an independent source
            row = conn.execute(
                """SELECT COUNT(*) AS n FROM story_article sa JOIN article b ON b.id = sa.article_id JOIN source sb ON sb.id = b.source_id
                   JOIN source sa2 ON sa2.id = ? WHERE sa.story_id = ? AND (sb.parent_org = sa2.parent_org OR b.title = ?)""",
                (a["source_id"], match, a["title"]),
            ).fetchone()
            is_synd = 1 if row and row["n"] > 0 else 0
            conn.execute(
                "INSERT OR IGNORE INTO story_article(story_id, article_id, is_syndicated) VALUES (?, ?, ?)",
                (match, a["id"], is_synd),
            )
            conn.execute(
                """UPDATE story SET last_seen = MAX(last_seen, ?), n_articles = n_articles + 1,
                     n_independent = n_independent + ? WHERE id = ?""",
                (ts, 0 if is_synd else 1, match),
            )
            attached += 1
            syndicated += is_synd
    conn.commit()
    return {"stories_created": created, "attached": attached, "syndicated": syndicated}


def articles_needing_body(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT a.id, a.url, a.source_id FROM article a JOIN source s ON s.id = a.source_id
           WHERE a.body_status = 'none' AND s.fetch_body = 1 AND s.paywall = 0 ORDER BY a.fetched_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def set_article_body(
    conn: sqlite3.Connection,
    aid: str,
    *,
    text: str | None,
    status: str,
    raw_path: str | None,
    sha256: str | None,
) -> None:
    conn.execute(
        "UPDATE article SET text = COALESCE(?, text), body_status = ?, raw_path = COALESCE(?, raw_path), sha256 = COALESCE(?, sha256) WHERE id = ?",
        (text, status, raw_path, sha256, aid),
    )


def fetch_log_for_day(conn: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT f.source_id, s.tier, s.enabled, COUNT(*) AS fetches, SUM(f.items_new) AS items_new, SUM(f.items_seen) AS items_seen,
                  SUM(f.market_points) AS market_points, SUM(CASE WHEN f.error IS NOT NULL OR f.status >= 400 THEN 1 ELSE 0 END) AS errors,
                  SUM(f.not_modified) AS not_modified, MAX(f.fetched_at) AS last_fetch, st.health, st.interval_s, st.last_error
           FROM fetch_log f JOIN source s ON s.id = f.source_id LEFT JOIN source_stats st ON st.source_id = f.source_id
           WHERE substr(f.fetched_at, 1, 10) = ? GROUP BY f.source_id ORDER BY s.tier, f.source_id""",
        (day,),
    ).fetchall()
