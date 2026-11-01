"""Parser registry (name in sources.yaml -> pure function) and per-source request planning (keyed APIs and
multi-series sources expand into several requests). rss/html/api adapters live beside this file; playwright and
pdf arrive in later phases."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from macroweb.collect.fetchers.api import (
    parse_cftc_cot,
    parse_ecos,
    parse_fiscaldata,
    parse_fred_csv,
    parse_fred_json,
    parse_hn_algolia,
    parse_kalshi,
    parse_polymarket,
    parse_stooq_csv,
)
from macroweb.collect.fetchers.html import parse_fomc_calendar, parse_trendforce_press
from macroweb.collect.fetchers.rss import parse_gnews_rss, parse_rss
from macroweb.collect.models import ParseResult
from macroweb.config import Source

Parser = Callable[[bytes, Source, str], ParseResult]

PARSERS: dict[str, Parser] = {
    "rss_default": parse_rss,
    "gnews_rss_v1": parse_gnews_rss,
    "fomc_calendar_v1": parse_fomc_calendar,
    "trendforce_press_v1": parse_trendforce_press,
    "fred_v1": parse_fred_json,
    "fred_csv_v1": parse_fred_csv,
    "fiscaldata_v1": parse_fiscaldata,
    "ecos_v1": parse_ecos,
    "polymarket_v1": parse_polymarket,
    "kalshi_v1": parse_kalshi,
    "cftc_cot_v1": parse_cftc_cot,
    "hn_algolia_v1": parse_hn_algolia,
    "stooq_csv_v1": parse_stooq_csv,
}
NOT_IMPLEMENTED_KINDS = {"playwright", "pdf"}


def get_parser(name: str) -> Parser:
    try:
        return PARSERS[name]
    except KeyError as exc:
        raise KeyError(f"no parser registered for {name!r} (add it to fetchers/__init__.py)") from exc


def parser_for_fixture(src: Source, url: str) -> Parser:
    """FRED fixtures may be fredgraph CSV while the live path is the JSON API."""
    if src.parser == "fred_v1" and "fredgraph.csv" in url:
        return parse_fred_csv
    return get_parser(src.parser)


def plan_requests(src: Source, env: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """(url, label) pairs for one collection of `src`. Credentials come from the environment variable named
    in `auth_env`; the caller redacts URLs before persisting them."""
    env = env if env is not None else dict(os.environ)
    key = env.get(src.auth_env) if src.auth_env else None
    if src.auth_env and not key:
        return []
    today = datetime.now(UTC).date()
    if src.parser == "fred_v1":
        start = (today - timedelta(days=int(src.params.get("lookback_days", 800)))).isoformat()
        return [
            (f"{src.url}?series_id={sid}&api_key={key}&file_type=json&observation_start={start}", sid)
            for sid in src.params.get("series", [])
        ]
    if src.parser == "ecos_v1":
        lookback = int(src.params.get("lookback_days", 400))
        start = (today - timedelta(days=lookback)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        out = []
        for st in src.params.get("stats", []):
            cycle = st.get("cycle", "D")
            s, e = (start, end) if cycle == "D" else (start[:6], end[:6])
            out.append(
                (
                    f"{src.url.rstrip('/')}/StatisticSearch/{key}/json/kr/1/1000/{st['stat']}/{cycle}/{s}/{e}/{st['item']}",
                    st.get("name", st["stat"]),
                )
            )
        return out
    if src.parser == "kalshi_v1" and src.params.get("series_tickers"):
        sep = "&" if "?" in src.url else "?"
        return [
            (f"{src.url}{sep}series_ticker={t}&status=open&limit=100", t)
            for t in src.params["series_tickers"]
        ]
    if src.parser == "hn_algolia_v1":
        queries = src.params.get("queries") or ["nvidia"]
        sep = "&" if "?" in src.url else "?"
        return [(f"{src.url}{sep}query={quote_plus(q)}", q) for q in queries]
    return [(src.url, "main")]
