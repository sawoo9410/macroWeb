"""Golden tests for parsers: each fixture in tests/fixtures/<source>/ is parsed and a compact summary is
compared with `<fixture>.golden.json`. Summaries exclude volatile fields (snapshot-dated market points keep
only their keys) so a golden file changes only when parsing changes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from macroweb.collect.fetchers import parser_for_fixture
from macroweb.collect.fixtures import list_fixtures, read_fixture
from macroweb.collect.models import ParseResult
from macroweb.config import Source, load_sources


def golden_path(fixture: Path) -> Path:
    name = fixture.name[: -len(".gz")] if fixture.name.endswith(".gz") else fixture.name
    stem = name.rsplit(".", 1)[0]
    return fixture.with_name(f"{stem}.golden.json")


def summarize(result: ParseResult) -> dict[str, Any]:
    items = [
        {
            "title": i.title[:120],
            "url": i.url[:200],
            "published_at": i.published_at.isoformat(timespec="seconds") if i.published_at else None,
            "lang": i.lang,
            "has_summary": bool(i.summary),
        }
        for i in result.items[:3]
    ]
    keys = sorted({p.key for p in result.market})
    return {
        "n_items": len(result.items),
        "n_market": len(result.market),
        "market_keys": keys[:40],
        "first_items": items,
        "feed_window_known": result.feed_window_s is not None,
        "notes": result.notes[:5],
    }


def run_fixture(src: Source, fixture: Path, meta: dict[str, Any]) -> dict[str, Any]:
    parser = parser_for_fixture(src, meta.get("final_url") or meta.get("url") or src.url)
    content = read_fixture(fixture)
    return summarize(parser(content, src, meta.get("final_url") or src.url))


def iter_cases() -> list[tuple[Source, Path, dict[str, Any]]]:
    out = []
    for src in load_sources().sources:
        for fixture, meta in list_fixtures(src.id):
            out.append((src, fixture, meta))
    return out


def write_all(force: bool = False) -> list[tuple[Path, str]]:
    results = []
    for src, fixture, meta in iter_cases():
        gp = golden_path(fixture)
        if gp.exists() and not force:
            results.append((gp, "exists"))
            continue
        gp.write_text(
            json.dumps(run_fixture(src, fixture, meta), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        results.append((gp, "written"))
    return results


def check_all() -> list[tuple[str, str]]:
    failures = []
    for src, fixture, meta in iter_cases():
        gp = golden_path(fixture)
        name = f"{src.id}/{fixture.name}"
        if not gp.exists():
            failures.append((name, "missing golden — run `uv run macroweb source golden --write`"))
            continue
        expected = json.loads(gp.read_text(encoding="utf-8"))
        actual = run_fixture(src, fixture, meta)
        if actual != expected:
            diff = {
                k: (expected.get(k), actual.get(k))
                for k in set(expected) | set(actual)
                if expected.get(k) != actual.get(k)
            }
            failures.append((name, json.dumps(diff, ensure_ascii=False)[:400]))
    return failures
