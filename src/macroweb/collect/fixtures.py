"""Real-response fixtures for golden tests (PLAN §4.3: source 1 = adapter 1 + fixture 1 + golden 1).
`macroweb source capture <id>` saves `tests/fixtures/<id>/<date>.<ext>` + `.meta.json`; tests never touch
the network. Fixtures hold public documents only; no cookies or personal data are written."""

from __future__ import annotations

import gzip
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from macroweb.collect.http import ext_for, fetch_url
from macroweb.collect.models import FetchResponse
from macroweb.collect.redact import redact_url
from macroweb.config import Source
from macroweb.paths import ROOT

FIXTURES_DIR = ROOT / "tests" / "fixtures"


def fixture_dir(source_id: str) -> Path:
    return FIXTURES_DIR / source_id


def capture_url(source_id: str) -> str | None:
    """Which URL a fixture should come from; per-source overrides for multi-request sources."""
    return None


def save_fixture(src: Source, resp: FetchResponse, day: date | None = None, suffix: str = "") -> Path:
    day = day or datetime.now(UTC).date()
    d = fixture_dir(src.id)
    d.mkdir(parents=True, exist_ok=True)
    ext = ext_for(resp.content_type, resp.final_url)
    stem = f"{day.isoformat()}{suffix}"
    body = d / f"{stem}.{ext}"
    body.write_bytes(resp.content)
    secrets = [v for k, v in os.environ.items() if k.endswith(("_API_KEY", "_TOKEN", "_SECRET")) and v]
    meta = {
        "source_id": src.id,
        "url": redact_url(resp.url, secrets),
        "final_url": redact_url(resp.final_url, secrets),
        "status": resp.status,
        "content_type": resp.content_type,
        "fetched_at": (resp.fetched_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "size": len(resp.content),
        "parser": src.parser,
    }
    (d / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return body


def capture(src: Source, client: httpx.Client, url: str | None = None, suffix: str = "") -> Path:
    resp = fetch_url(client, url or src.url)
    if resp.status >= 400:
        raise RuntimeError(f"{src.id}: HTTP {resp.status} for {url or src.url}")
    return save_fixture(src, resp, suffix=suffix)


def read_fixture(path: Path) -> bytes:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as fh:
            return fh.read()
    return path.read_bytes()


def list_fixtures(source_id: str) -> list[tuple[Path, dict]]:
    d = fixture_dir(source_id)
    out: list[tuple[Path, dict]] = []
    if not d.exists():
        return out
    for meta in sorted(d.glob("*.meta.json")):
        stem = meta.name[: -len(".meta.json")]
        bodies = [p for p in d.glob(f"{stem}.*") if not p.name.endswith((".meta.json", ".golden.json"))]
        if bodies:
            out.append((bodies[0], json.loads(meta.read_text(encoding="utf-8"))))
    return out
