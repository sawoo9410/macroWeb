"""On-demand body fetch before extraction (ensure_bodies) with a real ECB page served by MockTransport."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from macroweb.collect.fixtures import list_fixtures, read_fixture
from macroweb.collect.http import make_client
from macroweb.collect.pipeline import run_collect
from macroweb.config import load_extract, load_sources
from macroweb.db import repo
from macroweb.extract.bodies import ensure_bodies
from macroweb.extract.select import select_candidates

PAGE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "_pages" / "ecb_press_monetary_policy_decisions.html"
)
NOW = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)


def _transport(robots_status: int) -> httpx.MockTransport:
    srcs = {s.id: s for s in load_sources().sources}
    fx, meta = list_fixtures("ecb_press")[0]
    feed = read_fixture(fx)
    page = PAGE.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == srcs["ecb_press"].url:
            return httpx.Response(
                200, content=feed, headers={"content-type": meta.get("content_type", "application/xml")}
            )
        if request.url.path == "/robots.txt":
            return httpx.Response(
                robots_status, text="User-agent: *\nDisallow: /\n" if robots_status == 200 else ""
            )
        if "ecb.europa.eu" in url:
            return httpx.Response(200, content=page, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_ensure_bodies_fetches_ecb_statements_before_extraction() -> None:
    sources = {s.id: s for s in load_sources().sources}
    with make_client(transport=_transport(robots_status=404)) as client:
        run_collect(
            "2026-11-02", source_ids=["ecb_press"], force=True, bodies=False, client=client, now=NOW, env={}
        )
        conn = repo.connect()
        try:
            cands = select_candidates(conn, prompt_version=load_extract().prompt.version, limit=5, now=NOW)
            assert cands and all(len(c.story.text) < 60 for c in cands), (
                "ECB RSS has no description: candidates start text-less"
            )
            keep, rep = ensure_bodies(conn, cands, sources, max_fetch=5, client=client)
            assert rep.attempted == min(5, len(cands)) and rep.fetched == len(keep) and len(keep) >= 1
            assert all(len(c.story.text) > 500 for c in keep)
            assert "Governing Council" in keep[0].story.text
            row = conn.execute(
                "SELECT body_status, raw_path FROM article WHERE id = ?",
                (keep[0].story.extra["rep_article_id"],),
            ).fetchone()
            assert row["body_status"] == "fetched" and row["raw_path"].endswith(".html.gz")
        finally:
            conn.close()


def test_ensure_bodies_respects_robots_and_drops_textless() -> None:
    sources = {s.id: s for s in load_sources().sources}
    with make_client(transport=_transport(robots_status=200)) as client:
        run_collect(
            "2026-11-02", source_ids=["ecb_press"], force=True, bodies=False, client=client, now=NOW, env={}
        )
        conn = repo.connect()
        try:
            cands = select_candidates(conn, prompt_version=load_extract().prompt.version, limit=3, now=NOW)
            keep, rep = ensure_bodies(conn, cands, sources, max_fetch=3, client=client)
            assert keep == [] and rep.robots_disallow == len(cands) and len(rep.still_empty) == len(cands)
            n = conn.execute("SELECT COUNT(*) FROM article WHERE body_status = 'robots_disallow'").fetchone()[
                0
            ]
            assert n == len(cands)
        finally:
            conn.close()
