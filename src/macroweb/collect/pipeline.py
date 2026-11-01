"""`macroweb collect`: the 30-minute tick (PLAN §4.4). Due sources → conditional fetch → raw snapshot →
parse → articles/market → body fetch (robots-checked) → SimHash story grouping → daily stats → run row.
Idempotent: snapshots are content-addressed, articles keyed by canonical URL, market by (date, key)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from macroweb.collect import store
from macroweb.collect.fetchers import NOT_IMPLEMENTED_KINDS, get_parser, plan_requests
from macroweb.collect.fetchers.html import extract_body
from macroweb.collect.http import ext_for, fetch_url, make_client
from macroweb.collect.politeness import DomainThrottle
from macroweb.collect.redact import redact_url
from macroweb.collect.robots import RobotsCache
from macroweb.collect.scheduler import event_mode_active, is_due
from macroweb.collect.snapshot import save_raw
from macroweb.collect.stats import write_collect_stats
from macroweb.config import CalendarConfig, Source, load_sources, load_yaml
from macroweb.db import repo
from macroweb.paths import CONFIG_DIR

KST = ZoneInfo("Asia/Seoul")


@dataclass
class CollectSummary:
    day: str
    run_id: str | None = None
    due: int = 0
    fetched: int = 0
    ok: int = 0
    not_modified: int = 0
    skipped: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    items_seen: int = 0
    items_new: int = 0
    market_points: int = 0
    bodies: dict[str, int] = field(default_factory=dict)
    stories: dict[str, int] = field(default_factory=dict)
    event_mode: bool = False
    stats_path: Path | None = None
    elapsed_s: float = 0.0

    def exit_code(self) -> int:
        return 1 if self.due and self.ok == 0 and self.errors else 0

    def render(self) -> str:
        lines = [
            f"collect {self.day} run={self.run_id} due={self.due} fetched={self.fetched} ok={self.ok} 304={self.not_modified} "
            f"items new/seen={self.items_new}/{self.items_seen} market={self.market_points} event_mode={self.event_mode} {self.elapsed_s:.1f}s",
        ]
        if self.bodies:
            lines.append(f"bodies: {self.bodies}")
        if self.stories:
            lines.append(f"stories: {self.stories}")
        for sid, why in self.skipped.items():
            lines.append(f"skip {sid}: {why}")
        for sid, err in self.errors.items():
            lines.append(f"ERROR {sid}: {err}")
        if self.stats_path:
            lines.append(f"stats: {self.stats_path}")
        return "\n".join(lines)


def _secrets(env: dict[str, str]) -> list[str]:
    return [v for k, v in env.items() if k.endswith(("_API_KEY", "_TOKEN", "_SECRET")) and v]


def _as_dict(obj: object) -> dict:
    return {k: obj[k] for k in obj.keys()} if hasattr(obj, "keys") else {}  # type: ignore[index, attr-defined]


def run_collect(
    day: str | None = None,
    *,
    source_ids: list[str] | None = None,
    force: bool = False,
    bodies: bool = True,
    body_limit: int = 40,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    env: dict[str, str] | None = None,
) -> CollectSummary:
    t0 = time.monotonic()
    now = now or datetime.now(UTC)
    env = env if env is not None else dict(os.environ)
    day = day or now.astimezone(KST).date().isoformat()
    summary = CollectSummary(day=day)
    repo.init_db()
    conn = repo.connect()
    own_client = client is None
    client = client or make_client()
    try:
        sources = load_sources().sources
        store.sync_sources(conn, sources)
        calendar = CalendarConfig.model_validate(load_yaml(CONFIG_DIR / "calendar.yaml"))
        summary.event_mode = event_mode_active(now, calendar.events)
        summary.run_id = repo.start_run(conn, "collect")
        stats = store.all_stats(conn)
        throttle = DomainThrottle()
        secrets = _secrets(env)
        for src in sources:
            if not src.enabled or (source_ids and src.id not in source_ids):
                continue
            st = stats.get(src.id)
            if not force and st is not None and not is_due(st["next_due_at"], now):
                continue
            summary.due += 1
            if src.kind in NOT_IMPLEMENTED_KINDS:
                summary.skipped[src.id] = f"{src.kind} fetcher arrives in a later phase"
                continue
            if src.auth_env and not env.get(src.auth_env):
                summary.skipped[src.id] = f"{src.auth_env} not set"
                continue
            try:
                parser = get_parser(src.parser)
            except KeyError as exc:
                summary.errors[src.id] = str(exc)
                store.record_fetch(
                    conn,
                    src,
                    resp=None,
                    raw_path=None,
                    items_seen=0,
                    items_new=0,
                    market_points=0,
                    feed_window_s=None,
                    error=str(exc),
                    run_id=summary.run_id,
                    event_active=summary.event_mode,
                    now=now,
                )
                continue
            _collect_source(
                conn, src, parser, plan_requests(src, env), client, throttle, secrets, st, summary, now
            )
        conn.commit()
        if bodies:
            summary.bodies = _fetch_bodies(conn, client, throttle, body_limit, now)
        summary.stories = store.group_into_stories(conn)
        summary.stats_path = write_collect_stats(conn, day)
        summary.elapsed_s = time.monotonic() - t0
        repo.finish_run(
            conn,
            summary.run_id,
            "ok" if summary.exit_code() == 0 else "failed",
            {k: v for k, v in vars(summary).items() if k not in ("stats_path",)}
            | {"stats_path": str(summary.stats_path)},
        )
        return summary
    finally:
        conn.close()
        if own_client:
            client.close()


def _collect_source(
    conn, src: Source, parser, requests, client, throttle, secrets, st, summary: CollectSummary, now
) -> None:
    for url, label in requests:
        throttle.wait(url)
        etag = st["etag"] if (st is not None and label == "main") else None
        last_mod = st["last_modified"] if (st is not None and label == "main") else None
        try:
            resp = fetch_url(client, url, etag=etag, last_modified=last_mod)
        except httpx.HTTPError as exc:
            err = f"{type(exc).__name__}"
            summary.errors[src.id] = err
            store.record_fetch(
                conn,
                src,
                resp=None,
                raw_path=None,
                items_seen=0,
                items_new=0,
                market_points=0,
                feed_window_s=None,
                error=err,
                run_id=summary.run_id,
                event_active=summary.event_mode,
                now=now,
            )
            continue
        summary.fetched += 1
        resp.url = redact_url(resp.url, secrets)
        resp.final_url = redact_url(resp.final_url, secrets)
        if resp.not_modified:
            summary.not_modified += 1
            summary.ok += 1
            store.record_fetch(
                conn,
                src,
                resp=resp,
                raw_path=None,
                items_seen=0,
                items_new=0,
                market_points=0,
                feed_window_s=None,
                error=None,
                run_id=summary.run_id,
                event_active=summary.event_mode,
                now=now,
            )
            continue
        if resp.status >= 400:
            err = f"HTTP {resp.status}"
            summary.errors[src.id] = err
            store.record_fetch(
                conn,
                src,
                resp=resp,
                raw_path=None,
                items_seen=0,
                items_new=0,
                market_points=0,
                feed_window_s=None,
                error=err,
                run_id=summary.run_id,
                event_active=summary.event_mode,
                now=now,
            )
            continue
        snap = save_raw(
            src.id,
            resp.url,
            resp.content,
            ext=ext_for(resp.content_type, resp.final_url),
            status=resp.status,
            content_type=resp.content_type,
            final_url=resp.final_url,
            fetched_at=resp.fetched_at,
            kind=src.kind,
        )
        try:
            result = parser(resp.content, src, resp.final_url)
        except Exception as exc:  # noqa: BLE001 - a parser bug must not stop the other sources
            err = f"parse: {type(exc).__name__}: {str(exc)[:120]}"
            summary.errors[src.id] = err
            store.record_fetch(
                conn,
                src,
                resp=resp,
                raw_path=str(snap.path),
                items_seen=0,
                items_new=0,
                market_points=0,
                feed_window_s=None,
                error=err,
                run_id=summary.run_id,
                event_active=summary.event_mode,
                now=now,
            )
            continue
        new = 0
        for item in result.items:
            _, is_new = store.upsert_article(
                conn, src, item, raw_path=str(snap.path), sha256=snap.sha256, fetched_at=now
            )
            new += int(is_new)
        n_mkt = store.insert_market(conn, result.market)
        summary.ok += 1
        summary.items_seen += len(result.items)
        summary.items_new += new
        summary.market_points += n_mkt
        store.record_fetch(
            conn,
            src,
            resp=resp,
            raw_path=str(snap.path),
            items_seen=len(result.items),
            items_new=new,
            market_points=n_mkt,
            feed_window_s=result.feed_window_s,
            error=None,
            run_id=summary.run_id,
            event_active=summary.event_mode,
            now=now,
        )


def _fetch_bodies(conn, client, throttle: DomainThrottle, limit: int, now: datetime) -> dict[str, int]:
    robots = RobotsCache(client)
    counts = {"fetched": 0, "robots_disallow": 0, "failed": 0}
    for row in store.articles_needing_body(conn, limit):
        url = row["url"]
        if not robots.allowed(url):
            store.set_article_body(
                conn, row["id"], text=None, status="robots_disallow", raw_path=None, sha256=None
            )
            counts["robots_disallow"] += 1
            continue
        throttle.wait(url)
        try:
            resp = fetch_url(client, url)
        except httpx.HTTPError:
            store.set_article_body(conn, row["id"], text=None, status="failed", raw_path=None, sha256=None)
            counts["failed"] += 1
            continue
        if resp.status >= 400 or "html" not in resp.content_type.lower():
            store.set_article_body(conn, row["id"], text=None, status="failed", raw_path=None, sha256=None)
            counts["failed"] += 1
            continue
        snap = save_raw(
            row["source_id"],
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
            row["id"],
            text=text,
            status="fetched" if text else "failed",
            raw_path=str(snap.path),
            sha256=snap.sha256,
        )
        counts["fetched" if text else "failed"] += 1
    conn.commit()
    return counts
