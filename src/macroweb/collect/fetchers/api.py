"""JSON/CSV API parsers. Numeric series go to the `market` table (S-DATA: no LLM, PLAN §6.2.1); market
questions (Polymarket/Kalshi) and HN stories become items with their price/points in `extra`."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from macroweb.collect.models import Item, MarketPoint, ParseResult
from macroweb.config import Source


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _kw_match(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def _iso(dt: str | None) -> datetime | None:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def parse_fred_json(content: bytes, src: Source, url: str) -> ParseResult:
    data = json.loads(content)
    series = parse_qs(urlsplit(url).query).get("series_id", ["?"])[0]
    points = [
        MarketPoint(date=o["date"], key=f"FRED:{series}", value=float(o["value"]), source="fred")
        for o in data.get("observations", [])
        if o.get("value") not in (None, ".", "")
    ]
    return ParseResult(market=points)


def parse_fred_csv(content: bytes, src: Source, url: str) -> ParseResult:
    rows = list(csv.reader(io.StringIO(content.decode("utf-8", "replace"))))
    if not rows or len(rows[0]) < 2:
        return ParseResult(notes=["fredgraph: no header"])
    series = rows[0][1].strip()
    points = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in (".", ""):
            try:
                points.append(MarketPoint(date=r[0], key=f"FRED:{series}", value=float(r[1]), source="fred"))
            except ValueError:
                continue
    return ParseResult(market=points)


def parse_fiscaldata(content: bytes, src: Source, url: str) -> ParseResult:
    data = json.loads(content)
    points: list[MarketPoint] = []
    fields = {
        "tot_pub_debt_out_amt": "TOT_PUB_DEBT",
        "debt_held_public_amt": "DEBT_HELD_PUBLIC",
        "intragov_hold_amt": "INTRAGOV_HOLD",
    }
    for row in data.get("data", []):
        d = row.get("record_date")
        for col, key in fields.items():
            v = row.get(col)
            if d and v not in (None, "null", ""):
                points.append(MarketPoint(date=d, key=f"FISCAL:{key}", value=float(v), source="fiscaldata"))
    return ParseResult(market=points)


def parse_ecos(content: bytes, src: Source, url: str) -> ParseResult:
    data = json.loads(content)
    block = data.get("StatisticSearch") or {}
    rows = block.get("row") or []
    points: list[MarketPoint] = []
    notes: list[str] = []
    if "RESULT" in data:
        notes.append(f"ecos: {data['RESULT'].get('CODE')} {data['RESULT'].get('MESSAGE')}")
    for r in rows:
        t = str(r.get("TIME", ""))
        if len(t) == 8:
            d = f"{t[:4]}-{t[4:6]}-{t[6:]}"
        elif len(t) == 6:
            d = f"{t[:4]}-{t[4:]}-01"
        elif len(t) == 4:
            d = f"{t}-01-01"
        else:
            continue
        try:
            v = float(r.get("DATA_VALUE"))
        except (TypeError, ValueError):
            continue
        points.append(
            MarketPoint(
                date=d, key=f"ECOS:{r.get('STAT_CODE')}:{r.get('ITEM_CODE1')}", value=v, source="ecos"
            )
        )
    return ParseResult(market=points, notes=notes)


def parse_polymarket(content: bytes, src: Source, url: str) -> ParseResult:
    data = json.loads(content)
    keywords = list(src.params.get("keywords", []))
    items: list[Item] = []
    points: list[MarketPoint] = []
    today = _today()
    for m in data if isinstance(data, list) else data.get("markets", []):
        q = m.get("question") or ""
        if not q or not _kw_match(q, keywords):
            continue
        slug = m.get("slug") or str(m.get("id"))
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
            yes = float(prices[0]) if prices else None
        except (ValueError, TypeError, json.JSONDecodeError):
            yes = None
        items.append(
            Item(
                url=f"https://polymarket.com/market/{slug}",
                title=q,
                published_at=_iso(m.get("createdAt")),
                lang="en",
                extra={
                    "slug": slug,
                    "end_date": m.get("endDate"),
                    "volume": m.get("volume"),
                    "yes": yes,
                    "kind": "prediction_market",
                },
            )
        )
        if yes is not None:
            points.append(MarketPoint(date=today, key=f"PM:{slug}", value=yes, source="polymarket"))
    return ParseResult(items=items, market=points)


def parse_kalshi(content: bytes, src: Source, url: str) -> ParseResult:
    data = json.loads(content)
    keywords = list(src.params.get("keywords", []))
    items: list[Item] = []
    points: list[MarketPoint] = []
    today = _today()
    for m in data.get("markets", []):
        title = m.get("title") or ""
        if not title or not _kw_match(f"{title} {m.get('event_ticker', '')}", keywords):
            continue
        ticker = m.get("ticker")
        price: float | None = None
        for field in ("last_price_dollars", "yes_bid_dollars", "last_price"):
            v = m.get(field)
            if v not in (None, ""):
                try:
                    price = float(v) / (100.0 if field == "last_price" else 1.0)
                    break
                except ValueError:
                    continue
        items.append(
            Item(
                url=f"https://kalshi.com/markets/{ticker}",
                title=title,
                published_at=_iso(m.get("open_time")),
                lang="en",
                extra={
                    "ticker": ticker,
                    "event_ticker": m.get("event_ticker"),
                    "close_time": m.get("close_time"),
                    "yes": price,
                    "kind": "prediction_market",
                },
            )
        )
        if price is not None and ticker:
            points.append(MarketPoint(date=today, key=f"KALSHI:{ticker}", value=price, source="kalshi"))
    return ParseResult(items=items, market=points)


def parse_cftc_cot(content: bytes, src: Source, url: str) -> ParseResult:
    """CFTC legacy futures-only short format (deafut.txt): name, yymmdd, date, codes..., OI, NC long, NC short,
    NC spread, Comm long, Comm short, Tot long, Tot short, NonRept long, NonRept short, ..."""
    wanted: dict[str, str] = dict(src.params.get("markets", {}))
    points: list[MarketPoint] = []
    reader = csv.reader(io.StringIO(content.decode("utf-8", "replace")))
    for row in reader:
        if len(row) < 17:
            continue
        name = row[0].strip()
        if wanted and name not in wanted:
            continue
        slug = wanted.get(name) or re.sub(r"[^A-Z0-9]+", "_", name.upper())[:24]
        date = row[2].strip()
        try:
            oi = int(row[7])
            nc_l = int(row[8])
            nc_s = int(row[9])
            c_l = int(row[11])
            c_s = int(row[12])
        except ValueError:
            continue
        points += [
            MarketPoint(date=date, key=f"COT:{slug}:OI", value=float(oi), source="cftc"),
            MarketPoint(date=date, key=f"COT:{slug}:NONCOMM_NET", value=float(nc_l - nc_s), source="cftc"),
            MarketPoint(date=date, key=f"COT:{slug}:COMM_NET", value=float(c_l - c_s), source="cftc"),
        ]
    return ParseResult(market=points)


def parse_hn_algolia(content: bytes, src: Source, url: str) -> ParseResult:
    data = json.loads(content)
    query = parse_qs(urlsplit(url).query).get("query", [""])[0]
    items: list[Item] = []
    for h in data.get("hits", []):
        title = h.get("title") or ""
        oid = h.get("objectID")
        if not title or not oid:
            continue
        items.append(
            Item(
                url=h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                title=title,
                published_at=_iso(h.get("created_at")),
                lang="en",
                extra={
                    "points": h.get("points"),
                    "comments": h.get("num_comments"),
                    "hn_id": oid,
                    "query": query,
                    "kind": "community",
                },
            )
        )
    return ParseResult(items=items)


def parse_stooq_csv(content: bytes, src: Source, url: str) -> ParseResult:
    symbol = parse_qs(urlsplit(url).query).get("s", ["?"])[0].upper()
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8", "replace"))))
    points = []
    for r in rows:
        try:
            points.append(
                MarketPoint(date=r["Date"], key=f"STOOQ:{symbol}", value=float(r["Close"]), source="stooq")
            )
        except (KeyError, ValueError):
            continue
    return ParseResult(market=points, notes=[] if points else ["stooq: no CSV rows (bot challenge?)"])


def _unused(_: Any) -> None:  # keep `Any` import meaningful for type checkers on older pythons
    return None
