"""Every fixture under tests/fixtures/<source>/ must parse and match its .golden.json (PLAN §13.7: 소스당 골든 1+).
No network: fixtures are real responses captured with `macroweb source capture`."""

from __future__ import annotations

import json

import pytest

from macroweb.collect.golden import golden_path, iter_cases, run_fixture

CASES = iter_cases()
IDS = [f"{src.id}/{fx.name}" for src, fx, _ in CASES]


def test_every_enabled_keyless_source_has_a_fixture() -> None:
    from macroweb.config import load_sources

    covered = {src.id for src, _, _ in CASES}
    missing = [
        s.id
        for s in load_sources().sources
        if s.enabled and not s.auth_env and s.kind not in ("playwright", "pdf") and s.id not in covered
    ]
    assert not missing, f"sources without fixtures: {missing}"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_fixture_matches_golden(case) -> None:
    src, fixture, meta = case
    gp = golden_path(fixture)
    assert gp.exists(), f"missing {gp.name}: run `uv run macroweb source golden --write`"
    expected = json.loads(gp.read_text(encoding="utf-8"))
    actual = run_fixture(src, fixture, meta)
    assert actual == expected


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_fixture_yields_content(case) -> None:
    src, fixture, meta = case
    summary = run_fixture(src, fixture, meta)
    if src.kind in ("rss", "html") or src.parser in ("hn_algolia_v1",):
        assert summary["n_items"] > 0
        for it in summary["first_items"]:
            assert it["url"].startswith("http") and it["title"]
    elif src.parser in (
        "fiscaldata_v1",
        "fred_v1",
        "fred_csv_v1",
        "cftc_cot_v1",
        "ecos_v1",
        # keyless market data (ADR-0005)
        "treasury_yield_v1",
        "ecb_exr_v1",
        "naver_world_index_v1",
        "naver_domestic_index_v1",
        "kraken_ohlc_v1",
    ):
        assert summary["n_market"] > 0
