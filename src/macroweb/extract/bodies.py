"""Fetch missing article bodies for stories about to be extracted (T0 statements, CBO notes, …) so the model never
sees a bare title (the first live run spent 3 calls on ECB items whose RSS carries no description). Same rules as
the collect tick: `fetch_body` sources only, no paywall, robots.txt honoured, per-domain throttle, raw snapshot."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import httpx

from macroweb.collect import store
from macroweb.collect.fetchers.html import extract_body
from macroweb.collect.http import fetch_url, make_client
from macroweb.collect.politeness import DomainThrottle
from macroweb.collect.robots import RobotsCache
from macroweb.collect.snapshot import save_raw
from macroweb.config import Source
from macroweb.extract.select import MIN_TEXT_CHARS, Candidate


@dataclass
class BodyReport:
    attempted: int = 0
    fetched: int = 0
    robots_disallow: int = 0
    failed: int = 0
    still_empty: list[str] = field(default_factory=list)


def ensure_bodies(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    sources: dict[str, Source],
    *,
    max_fetch: int = 10,
    client: httpx.Client | None = None,
) -> tuple[list[Candidate], BodyReport]:
    """Returns (candidates that have usable text, report). Candidates whose text stays empty are dropped."""
    report = BodyReport()
    own = client is None
    client = client or make_client()
    robots = RobotsCache(client)
    throttle = DomainThrottle()
    keep: list[Candidate] = []
    try:
        for cand in candidates:
            story = cand.story
            if len(story.text or "") >= MIN_TEXT_CHARS:
                keep.append(cand)
                continue
            src = sources.get(story.source_id)
            aid = str(story.extra.get("rep_article_id") or "")
            if not (src and src.fetch_body and not src.paywall and aid) or report.attempted >= max_fetch:
                report.still_empty.append(story.story_id)
                continue
            report.attempted += 1
            if not robots.allowed(story.url):
                store.set_article_body(
                    conn, aid, text=None, status="robots_disallow", raw_path=None, sha256=None
                )
                report.robots_disallow += 1
                report.still_empty.append(story.story_id)
                continue
            throttle.wait(story.url)
            try:
                resp = fetch_url(client, story.url)
            except httpx.HTTPError:
                resp = None
            if resp is None or resp.status >= 400 or "html" not in resp.content_type.lower():
                store.set_article_body(conn, aid, text=None, status="failed", raw_path=None, sha256=None)
                report.failed += 1
                report.still_empty.append(story.story_id)
                continue
            snap = save_raw(
                story.source_id,
                resp.url,
                resp.content,
                ext="html",
                status=resp.status,
                content_type=resp.content_type,
                final_url=resp.final_url,
                fetched_at=resp.fetched_at,
                kind="body",
            )
            text, _meta = extract_body(resp.content, resp.final_url)
            store.set_article_body(
                conn,
                aid,
                text=text,
                status="fetched" if text else "failed",
                raw_path=str(snap.path),
                sha256=snap.sha256,
            )
            if text and len(text) >= MIN_TEXT_CHARS:
                story.text = text
                report.fetched += 1
                keep.append(cand)
            else:
                report.failed += 1
                report.still_empty.append(story.story_id)
        conn.commit()
    finally:
        if own:
            client.close()
    return keep, report
