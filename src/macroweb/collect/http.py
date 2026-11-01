"""One HTTP path for every fetcher: declared UA, bounded body, conditional GET (ETag/Last-Modified),
timing. Tests inject an `httpx.MockTransport` client; nothing here opens a network connection on import."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx

from macroweb.collect.models import FetchResponse
from macroweb.collect.politeness import USER_AGENT

MAX_BYTES = 8_000_000


def make_client(timeout: float = 25.0, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        transport=transport,
    )


def fetch_url(
    client: httpx.Client,
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    max_bytes: int = MAX_BYTES,
) -> FetchResponse:
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    t0 = time.monotonic()
    with client.stream("GET", url, headers=headers) as r:
        chunks: list[bytes] = []
        total = 0
        if r.status_code != 304:
            for chunk in r.iter_bytes(chunk_size=65536):
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break
        content = b"".join(chunks)
        return FetchResponse(
            url=url,
            final_url=str(r.url),
            status=r.status_code,
            content=content,
            content_type=r.headers.get("content-type", ""),
            etag=r.headers.get("etag"),
            last_modified=r.headers.get("last-modified"),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            not_modified=r.status_code == 304,
            fetched_at=datetime.now(UTC),
        )


def ext_for(content_type: str, url: str) -> str:
    ct = content_type.lower()
    if "json" in ct:
        return "json"
    if "xml" in ct or url.endswith((".xml", ".rss")):
        return "xml"
    if "html" in ct:
        return "html"
    if "csv" in ct or url.endswith(".csv") or "fredgraph.csv" in url or "stooq.com/q/d/l" in url:
        return "csv"
    if "pdf" in ct:
        return "pdf"
    return "txt"
