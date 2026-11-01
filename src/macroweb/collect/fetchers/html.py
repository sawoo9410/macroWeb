"""HTML parsers (selectolax) for the two Phase-1 pages without feeds, plus body extraction (trafilatura)
used for `fetch_body` sources."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import trafilatura
from dateutil import parser as dateparser
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from macroweb.collect.models import Item, ParseResult
from macroweb.config import Source

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}
_DOC_KINDS = [
    (re.compile(r"/newsevents/pressreleases/monetary(\d{8})a\.htm$"), "statement"),
    (re.compile(r"/newsevents/pressreleases/monetary(\d{8})a1\.htm$"), "implementation_note"),
    (re.compile(r"/newsevents/pressreleases/monetary(\d{8})b\.htm$"), "longer_run_goals"),
    (re.compile(r"/monetarypolicy/fomcminutes(\d{8})\.htm$"), "minutes"),
    (re.compile(r"/monetarypolicy/fomcpres?s?conf(\d{8})\.htm$"), "press_conference"),
    (re.compile(r"/monetarypolicy/fomcprojtabl(\d{8})\.htm$"), "projections"),
]
_RELEASED = re.compile(r"Released\s+([A-Z][a-z]+ \d{1,2}, \d{4})")


def parse_fomc_calendar(content: bytes, src: Source, url: str) -> ParseResult:
    tree = HTMLParser(content)
    items: list[Item] = []
    notes: list[str] = []
    seen: set[str] = set()
    for panel in tree.css("div.panel.panel-default"):
        heading = panel.css_first("div.panel-heading")
        m = re.search(r"(20\d{2})", heading.text() if heading else "")
        if not m:
            continue
        year = int(m.group(1))
        min_year = int(src.params.get("min_year", datetime.now(UTC).year - 2))
        if year < min_year:
            continue
        for row in panel.css("div.fomc-meeting"):
            month_node = row.css_first(".fomc-meeting__month")
            date_node = row.css_first(".fomc-meeting__date")
            if not month_node or not date_node:
                continue
            month_txt = month_node.text(strip=True)
            month = next((n for name, n in MONTHS.items() if name.lower() in month_txt.lower()), None)
            date_txt = date_node.text(strip=True)
            days = [int(d) for d in re.findall(r"\d{1,2}", date_txt)]
            has_sep = "*" in date_txt
            if month and days:
                notes.append(
                    f"meeting:{year}-{month:02d}-{days[0]:02d}..{days[-1]:02d}{'*' if has_sep else ''}"
                )
            row_text = row.text(separator=" ")
            released = _RELEASED.search(row_text)
            minutes_dt = dateparser.parse(released.group(1)).replace(tzinfo=UTC) if released else None
            for a in row.css("a"):
                href = a.attributes.get("href") or ""
                for rx, kind in _DOC_KINDS:
                    mm = rx.search(href)
                    if not mm:
                        continue
                    ymd = mm.group(1)
                    full = urljoin(url, href)
                    if full in seen:
                        break
                    seen.add(full)
                    meeting_dt = datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]), tzinfo=UTC)
                    label = {
                        "statement": "FOMC statement",
                        "implementation_note": "FOMC implementation note",
                        "longer_run_goals": "FOMC statement on longer-run goals",
                        "minutes": "FOMC minutes",
                        "press_conference": "FOMC press conference",
                        "projections": "FOMC projection materials (SEP)",
                    }[kind]
                    items.append(
                        Item(
                            url=full,
                            title=f"{label} {meeting_dt.date().isoformat()}",
                            published_at=minutes_dt if kind == "minutes" and minutes_dt else meeting_dt,
                            lang="en",
                            extra={"kind": kind, "meeting": ymd, "year": year, "sep": has_sep},
                        )
                    )
                    break
    return ParseResult(items=items, notes=notes)


def parse_trendforce_press(content: bytes, src: Source, url: str) -> ParseResult:
    tree = HTMLParser(content)
    items: list[Item] = []
    stamps: list[datetime] = []
    for node in tree.css("div.list-item"):
        a = node.css_first("a.title-link")
        if not a or not a.attributes.get("href"):
            continue
        title = a.text(strip=True)
        href = urljoin(url, a.attributes["href"])
        date_node = node.css_first("h4")
        published = None
        if date_node:
            try:
                published = dateparser.parse(date_node.text(strip=True)).replace(tzinfo=UTC)
                stamps.append(published)
            except (ValueError, OverflowError):
                published = None
        p = node.css_first("p")
        summary = " ".join(p.text(separator=" ").split())[:2000] if p else None
        items.append(Item(url=href, title=title, summary=summary, published_at=published, lang="en"))
    window = int((max(stamps) - min(stamps)).total_seconds()) if len(stamps) >= 2 else None
    return ParseResult(items=items, feed_window_s=window)


def extract_body(html: bytes, url: str) -> tuple[str | None, dict[str, Any]]:
    """Main-text extraction for article pages. Returns (text, meta). Paywalled sources never get here."""
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            output_format="txt",
        )
    except Exception as exc:  # noqa: BLE001
        return None, {"error": type(exc).__name__}
    if not text or len(text) < 200:
        return None, {"error": "too_short"}
    return text, {"chars": len(text)}
