"""RSS/Atom parsers (feedparser). `rss_default` serves most T0–T2 feeds; `gnews_rss_v1` additionally records the
publisher that Google News appends to the title ("… - Reuters")."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import Any

import feedparser
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from macroweb.collect.models import Item, ParseResult
from macroweb.config import Source
from macroweb.normalize.lang import detect_lang


def _struct_to_dt(st: Any) -> datetime | None:
    if not st:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(st), tz=UTC)
    except (OverflowError, ValueError, TypeError):
        return None


def strip_html(text: str | None, limit: int = 2000) -> str | None:
    if not text:
        return None
    try:
        plain = HTMLParser(text).text(separator=" ", strip=True)
    except Exception:  # noqa: BLE001 - selectolax raises on odd input; fall back to the raw string
        plain = text
    plain = " ".join(plain.split())
    return plain[:limit] or None


def _entry_summary(entry: Any) -> tuple[str | None, str | None]:
    """(summary, full_text). Feeds that embed the article (content:encoded) give us the body for free."""
    content = entry.get("content")
    if content and isinstance(content, list) and content[0].get("value"):
        full = strip_html(content[0]["value"], limit=200_000)
        if full and len(full) > 1500:
            return full[:2000], full
        return full, None
    return strip_html(entry.get("summary") or entry.get("description")), None


def parse_rss(content: bytes, src: Source, url: str) -> ParseResult:
    feed = feedparser.parse(content)
    items: list[Item] = []
    stamps: list[datetime] = []
    for e in feed.entries:
        link = e.get("link") or (e.get("links") or [{}])[0].get("href")
        title = (e.get("title") or "").strip()
        if not link or not title:
            continue
        published = _struct_to_dt(e.get("published_parsed") or e.get("updated_parsed"))
        if published:
            stamps.append(published)
        summary, full_text = _entry_summary(e)
        author = (e.get("author") or "").strip() or None
        items.append(
            Item(
                url=link,
                title=title,
                summary=summary,
                published_at=published,
                author=author,
                text=full_text,
                lang=detect_lang(title, default=detect_lang(summary, default=src.lang)),
                extra={
                    k: v
                    for k, v in {
                        "guid": e.get("id"),
                        "tags": [t.get("term") for t in e.get("tags", [])][:8] or None,
                    }.items()
                    if v
                },
            )
        )
    window = int((max(stamps) - min(stamps)).total_seconds()) if len(stamps) >= 2 else None
    notes = []
    if feed.bozo and getattr(feed, "bozo_exception", None):
        notes.append(f"bozo: {type(feed.bozo_exception).__name__}")
    return ParseResult(items=items, feed_window_s=window, notes=notes)


def parse_gnews_rss(content: bytes, src: Source, url: str) -> ParseResult:
    result = parse_rss(content, src, url)
    for item in result.items:
        if " - " in item.title:
            head, _, publisher = item.title.rpartition(" - ")
            if head and publisher and len(publisher) <= 40:
                item.extra["publisher"] = publisher.strip()
                item.title = head.strip()
    return result
