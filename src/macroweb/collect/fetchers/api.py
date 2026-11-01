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


# --- keyless market data (ADR-0005): T0 Treasury/ECB, T3 Naver/Kraken ---------------------------------
def _num(text: str | None) -> float | None:
    """'10,688.80' -> 10688.8; None/''/'-' -> None."""
    if text is None:
        return None
    t = str(text).replace(",", "").strip()
    if t in ("", "-", "."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


UST_TENORS: dict[str, str] = {
    "BC_1MONTH": "1M",
    "BC_3MONTH": "3M",
    "BC_6MONTH": "6M",
    "BC_1YEAR": "1Y",
    "BC_2YEAR": "2Y",
    "BC_5YEAR": "5Y",
    "BC_10YEAR": "10Y",
    "BC_30YEAR": "30Y",
}
UST_SPREADS: tuple[tuple[str, str, str], ...] = (("10Y2Y", "10Y", "2Y"), ("10Y3M", "10Y", "3M"))


def parse_treasury_yield_curve(content: bytes, src: Source, url: str) -> ParseResult:
    """home.treasury.gov daily par yield curve (Atom/OData XML, one <entry> per business day).
    Keys UST:<tenor> plus computed spreads UST:10Y2Y / UST:10Y3M (percentage points)."""
    import xml.etree.ElementTree as ET

    ns_d = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
    ns_m = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        return ParseResult(notes=[f"treasury: xml parse error {exc}"])
    points: list[MarketPoint] = []
    for props in root.iter(f"{ns_m}properties"):
        date_el = props.find(f"{ns_d}NEW_DATE")
        if date_el is None or not (date_el.text or "").strip():
            continue
        day = (date_el.text or "").strip()[:10]
        tenor_vals: dict[str, float] = {}
        for field, tenor in UST_TENORS.items():
            el = props.find(f"{ns_d}{field}")
            v = _num(el.text if el is not None else None)
            if v is not None:
                tenor_vals[tenor] = v
                points.append(MarketPoint(date=day, key=f"UST:{tenor}", value=v, source="treasury"))
        for name, a, b in UST_SPREADS:
            if a in tenor_vals and b in tenor_vals:
                spread = round(tenor_vals[a] - tenor_vals[b], 4)
                points.append(MarketPoint(date=day, key=f"UST:{name}", value=spread, source="treasury"))
    return ParseResult(market=points, notes=[] if points else ["treasury: no entries"])


def parse_ecb_exr(content: bytes, src: Source, url: str) -> ParseResult:
    """ECB reference rates (SDMX csvdata: KEY,…,CURRENCY,…,TIME_PERIOD,OBS_VALUE). Quoted as <CUR> per EUR and
    stored as ECB:<CUR>_EUR; USD crosses are derived from the same 14:15 CET fixing as
    ECB:USD_<CUR>_CROSS = <CUR>_EUR / USD_EUR."""
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8", "replace"))))
    per_eur: dict[tuple[str, str], float] = {}
    points: list[MarketPoint] = []
    for r in rows:
        cur, day, val = r.get("CURRENCY"), r.get("TIME_PERIOD"), _num(r.get("OBS_VALUE"))
        if not cur or not day or val is None or len(day) != 10:
            continue
        per_eur[(day, cur)] = val
        points.append(MarketPoint(date=day, key=f"ECB:{cur}_EUR", value=val, source="ecb"))
    for (day, cur), val in sorted(per_eur.items()):
        usd = per_eur.get((day, "USD"))
        if cur != "USD" and usd:
            cross = round(val / usd, 6)
            points.append(MarketPoint(date=day, key=f"ECB:USD_{cur}_CROSS", value=cross, source="ecb"))
    return ParseResult(market=points, notes=[] if points else ["ecb: no observations"])


def parse_naver_world_index(content: bytes, src: Source, url: str) -> ParseResult:
    """api.stock.naver.com/index/<symbol>/price — daily closes of world indices (.SOX, .INX, .VIX, .DXY …).
    Dates are the exchange-local trading day taken from localTradedAt."""
    data = json.loads(content)
    if not isinstance(data, list):
        return ParseResult(notes=["naver_world: unexpected payload"])
    path = urlsplit(url).path
    path_sym = path.split("/index/")[-1].split("/")[0] if "/index/" in path else "?"
    points: list[MarketPoint] = []
    for row in data:
        sym = row.get("worldIndexSymbol") or path_sym
        day = (row.get("localTradedAt") or "")[:10]
        val = _num(row.get("closePrice"))
        if len(day) == 10 and val is not None:
            points.append(MarketPoint(date=day, key=f"NAVER:{sym}", value=val, source="naver"))
    return ParseResult(market=points, notes=[] if points else ["naver_world: no rows"])


def parse_naver_domestic_index(content: bytes, src: Source, url: str) -> ParseResult:
    """polling.finance.naver.com realtime KOSPI/KOSDAQ. Only marketStatus == CLOSE is recorded (one close per
    trading day, dated by localTradedAt); intraday values are never written to `market`."""
    data = json.loads(content)
    points: list[MarketPoint] = []
    notes: list[str] = []
    rows = data.get("datas", []) if isinstance(data, dict) else []
    for row in rows:
        code = row.get("itemCode") or row.get("symbolCode")
        status = row.get("marketStatus")
        if status != "CLOSE":
            notes.append(f"naver_domestic: {code} marketStatus={status} (skipped)")
            continue
        day = (row.get("localTradedAt") or "")[:10]
        val = _num(row.get("closePriceRaw") or row.get("closePrice"))
        if code and len(day) == 10 and val is not None:
            points.append(MarketPoint(date=day, key=f"NAVER:{code}", value=val, source="naver"))
    return ParseResult(market=points, notes=notes)


def parse_kraken_ohlc(content: bytes, src: Source, url: str) -> ParseResult:
    """api.kraken.com/0/public/OHLC daily candles. Only committed candles (time <= result.last) are kept; the
    in-progress candle is dropped. Key KRAKEN:<pair from the query>, value = close, date = UTC candle day."""
    data = json.loads(content)
    if data.get("error"):
        return ParseResult(notes=[f"kraken: {data['error']}"])
    result = data.get("result") or {}
    last = int(result.get("last") or 0)
    pair = parse_qs(urlsplit(url).query).get("pair", ["?"])[0].upper()
    points: list[MarketPoint] = []
    for k, candles in result.items():
        if k == "last" or not isinstance(candles, list):
            continue
        for c in candles:
            try:
                t, close = int(c[0]), float(c[4])
            except (IndexError, TypeError, ValueError):
                continue
            if last and t > last:
                continue
            day = datetime.fromtimestamp(t, tz=UTC).date().isoformat()
            points.append(MarketPoint(date=day, key=f"KRAKEN:{pair}", value=close, source="kraken"))
    return ParseResult(market=points, notes=[] if points else ["kraken: no committed candles"])
