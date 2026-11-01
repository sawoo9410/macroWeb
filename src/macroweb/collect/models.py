"""Data carried between fetchers, parsers and the store (PLAN §4.3). Parsers are pure: bytes -> ParseResult."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FetchResponse:
    url: str
    final_url: str
    status: int
    content: bytes
    content_type: str
    etag: str | None
    last_modified: str | None
    elapsed_ms: int
    not_modified: bool = False
    fetched_at: datetime | None = None


@dataclass
class Item:
    """One article/document reference produced by a parser."""

    url: str
    title: str
    summary: str | None = None
    published_at: datetime | None = None
    author: str | None = None
    text: str | None = None
    lang: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketPoint:
    date: str  # YYYY-MM-DD
    key: str  # e.g. FRED:DGS10, STOOQ:^SPX, FISCAL:TOT_PUB_DEBT
    value: float
    source: str


@dataclass
class ParseResult:
    items: list[Item] = field(default_factory=list)
    market: list[MarketPoint] = field(default_factory=list)
    feed_window_s: int | None = None  # newest - oldest item timestamp; drives the adaptive interval
    notes: list[str] = field(default_factory=list)
