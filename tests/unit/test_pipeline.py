"""End-to-end collect against fixture bytes served by httpx.MockTransport (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from macroweb.collect.fixtures import list_fixtures, read_fixture
from macroweb.collect.http import make_client
from macroweb.collect.pipeline import run_collect
from macroweb.config import load_sources
from macroweb.db import repo

SOURCES = ["fed_press", "yna_economy", "polymarket_gamma", "fomc_calendar", "treasury_fiscaldata"]


def _transport() -> httpx.MockTransport:
    srcs = {s.id: s for s in load_sources().sources}
    table: dict[str, tuple[bytes, str]] = {}
    for sid in SOURCES:
        fixture, meta = list_fixtures(sid)[0]
        table[srcs[sid].url] = (read_fixture(fixture), meta.get("content_type", "application/octet-stream"))

    def handler(request: httpx.Request) -> httpx.Response:
        hit = table.get(str(request.url))
        if hit is None:
            return httpx.Response(404, content=b"not found")
        return httpx.Response(200, content=hit[0], headers={"content-type": hit[1], "etag": '"v1"'})

    return httpx.MockTransport(handler)


def test_collect_twice_is_idempotent() -> None:
    now = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)
    with make_client(transport=_transport()) as client:
        first = run_collect(
            "2026-11-02", source_ids=SOURCES, force=True, bodies=False, client=client, now=now, env={}
        )
        assert first.ok == len(SOURCES), first.render()
        assert first.items_new > 20 and first.market_points > 0
        assert first.stats_path and first.stats_path.exists()
        second = run_collect(
            "2026-11-02", source_ids=SOURCES, force=True, bodies=False, client=client, now=now, env={}
        )
        assert second.items_new == 0, second.render()
        assert second.ok == len(SOURCES)
    conn = repo.connect()
    try:
        n_articles = conn.execute("SELECT COUNT(*) FROM article").fetchone()[0]
        assert n_articles == first.items_new
        stories = conn.execute("SELECT COUNT(*) FROM story").fetchone()[0]
        assert 0 < stories <= n_articles
        rows = conn.execute(
            f"SELECT source_id, next_due_at, interval_s, health FROM source_stats WHERE source_id IN ({','.join('?' * len(SOURCES))})",
            SOURCES,
        ).fetchall()
        assert all(r["next_due_at"] and r["interval_s"] and r["health"] == "ok" for r in rows)
        assert conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0] == 2 * len(SOURCES)
        assert conn.execute("SELECT COUNT(*) FROM run WHERE job='collect' AND status='ok'").fetchone()[0] == 2
    finally:
        conn.close()
    assert not any(p.exists() and False for p in [])  # placeholder to keep structure explicit


def test_not_due_sources_are_skipped_and_failures_degrade() -> None:
    now = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"down")

    with make_client(transport=httpx.MockTransport(handler)) as client:
        for _ in range(3):
            s = run_collect(
                "2026-11-02",
                source_ids=["fed_press"],
                force=True,
                bodies=False,
                client=client,
                now=now,
                env={},
            )
            assert s.errors.get("fed_press") == "HTTP 503"
            assert s.exit_code() == 1
        quiet = run_collect(
            "2026-11-02", source_ids=["fed_press"], force=False, bodies=False, client=client, now=now, env={}
        )
        assert quiet.due == 0  # backed-off next_due_at is in the future
    conn = repo.connect()
    try:
        row = conn.execute(
            "SELECT health, consecutive_failures FROM source_stats WHERE source_id='fed_press'"
        ).fetchone()
        assert row["health"] == "degraded" and row["consecutive_failures"] == 3
    finally:
        conn.close()
