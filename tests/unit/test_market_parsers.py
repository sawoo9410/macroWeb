"""Keyless market-data adapters (ADR-0005): request planning, derived series, and the rules that keep
provisional values out of `market` (CLOSE-only for Naver domestic, committed candles only for Kraken)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from macroweb.collect.fetchers import plan_requests
from macroweb.collect.fetchers.api import (
    parse_ecb_exr,
    parse_kraken_ohlc,
    parse_naver_domestic_index,
    parse_naver_world_index,
    parse_treasury_yield_curve,
)
from macroweb.collect.fixtures import list_fixtures, read_fixture
from macroweb.config import Source, load_sources

SRC = {s.id: s for s in load_sources().sources}


def _fixture(source_id: str) -> tuple[bytes, str]:
    fixture, meta = list_fixtures(source_id)[0]
    return read_fixture(fixture), meta.get("final_url") or meta["url"]


def _by_key(points):
    out: dict[str, dict[str, float]] = {}
    for p in points:
        out.setdefault(p.key, {})[p.date] = p.value
    return out


# --- request planning ---------------------------------------------------------------------------------
def test_treasury_plans_previous_and_current_month() -> None:
    reqs = plan_requests(SRC["treasury_yield_curve"], env={})
    assert len(reqs) == 2
    today = datetime.now(UTC).date()
    assert reqs[1][1] == today.strftime("%Y%m")
    assert all("field_tdr_date_value_month=" in url for url, _ in reqs)
    assert reqs[0][1] < reqs[1][1]


def test_naver_world_plans_one_request_per_symbol() -> None:
    src = SRC["naver_world_index"]
    reqs = plan_requests(src, env={})
    assert [label for _, label in reqs] == src.params["symbols"]
    assert all(f"/index/{label}/price" in url for url, label in reqs)


def test_ecb_and_kraken_plans_carry_lookback() -> None:
    ((ecb_url, _),) = plan_requests(SRC["ecb_exr"], env={})
    assert "startPeriod=20" in ecb_url and "format=csvdata" in ecb_url
    ((kraken_url, _),) = plan_requests(SRC["kraken_ohlc"], env={})
    assert "since=" in kraken_url and "pair=XBTUSD" in kraken_url


def test_keyless_market_sources_do_not_need_env() -> None:
    for sid in (
        "treasury_yield_curve",
        "ecb_exr",
        "naver_world_index",
        "naver_domestic_index",
        "kraken_ohlc",
    ):
        assert SRC[sid].auth_env is None and SRC[sid].enabled, sid
        assert plan_requests(SRC[sid], env={}), sid


# --- parsers on real fixtures --------------------------------------------------------------------------
def test_treasury_spreads_are_differences_of_stored_tenors() -> None:
    content, url = _fixture("treasury_yield_curve")
    res = parse_treasury_yield_curve(content, SRC["treasury_yield_curve"], url)
    by = _by_key(res.market)
    assert {"UST:2Y", "UST:10Y", "UST:3M", "UST:10Y2Y", "UST:10Y3M"} <= set(by)
    for day, spread in by["UST:10Y2Y"].items():
        assert abs(spread - (by["UST:10Y"][day] - by["UST:2Y"][day])) < 1e-6
    assert all(p.source == "treasury" for p in res.market)
    assert all(len(p.date) == 10 for p in res.market)


def test_ecb_cross_rate_is_krw_per_eur_over_usd_per_eur() -> None:
    content, url = _fixture("ecb_exr")
    res = parse_ecb_exr(content, SRC["ecb_exr"], url)
    by = _by_key(res.market)
    assert {"ECB:USD_EUR", "ECB:KRW_EUR", "ECB:USD_KRW_CROSS"} <= set(by)
    for day, cross in by["ECB:USD_KRW_CROSS"].items():
        assert abs(cross - by["ECB:KRW_EUR"][day] / by["ECB:USD_EUR"][day]) < 1e-5
        assert 1000 < cross < 2000  # sanity band for USD/KRW
    assert "ECB:USD_USD_CROSS" not in by


def test_naver_world_uses_symbol_and_local_date() -> None:
    content, url = _fixture("naver_world_index")
    res = parse_naver_world_index(content, SRC["naver_world_index"], url)
    assert res.market and all(p.key == "NAVER:.SOX" for p in res.market)
    dates = [p.date for p in res.market]
    assert len(set(dates)) == len(dates)  # one close per trading day
    assert all(p.value > 0 for p in res.market)


def test_naver_domestic_records_only_closed_market() -> None:
    src = SRC["naver_domestic_index"]
    content, url = _fixture("naver_domestic_index")
    closed = parse_naver_domestic_index(content, src, url)
    assert {p.key for p in closed.market} == {"NAVER:KOSPI", "NAVER:KOSDAQ"}
    intraday = json.loads(content)
    for row in intraday["datas"]:
        row["marketStatus"] = "OPEN"
    res = parse_naver_domestic_index(json.dumps(intraday).encode(), src, url)
    assert res.market == [] and any("skipped" in n for n in res.notes)


def test_kraken_drops_in_progress_candle() -> None:
    src = SRC["kraken_ohlc"]
    content, url = _fixture("kraken_ohlc")
    data = json.loads(content)
    last = int(data["result"]["last"])
    res = parse_kraken_ohlc(content, src, url)
    assert res.market and all(p.key == "KRAKEN:XBTUSD" for p in res.market)
    newest = max(p.date for p in res.market)
    assert newest == datetime.fromtimestamp(last, tz=UTC).date().isoformat()
    n_total = len(data["result"]["XXBTZUSD"])
    assert len(res.market) == n_total - 1  # exactly the open candle is dropped


def test_kraken_error_payload_yields_note_not_points() -> None:
    src = Source(id="k", name="k", tier=3, kind="api", url="https://api.kraken.com/0/public/OHLC?pair=XBTUSD")
    res = parse_kraken_ohlc(b'{"error":["EQuery:Unknown asset pair"]}', src, src.url)
    assert res.market == [] and res.notes
