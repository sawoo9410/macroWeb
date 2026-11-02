from macroweb.config import TIER_PRIOR, load_models, load_quality, load_sources, validate_all


def test_all_config_and_prompt_files_validate() -> None:
    results = validate_all()
    bad = [(r.name, r.message) for r in results if not r.ok]
    assert not bad, bad
    assert len(results) >= 11


def test_sources_have_unique_ids_and_strata() -> None:
    sources = load_sources().sources
    ids = [s.id for s in sources]
    assert len(ids) == len(set(ids))
    assert len(sources) >= 20
    for s in sources:
        assert s.rate_limit_s >= 2.0, s.id
        assert s.credibility_prior is not None and s.credibility_prior == TIER_PRIOR[s.tier]
        if s.enabled:
            assert s.stratum is not None, f"{s.id} needs a stratum"
        if s.auth_env:
            assert s.probe_url, f"{s.id}: keyed API needs a keyless probe_url"


def test_models_config_tiers_and_budget() -> None:
    cfg = load_models()
    assert set(cfg.tiers) == {"small", "mid", "large"}
    assert cfg.tiers["small"].input < cfg.tiers["mid"].input < cfg.tiers["large"].input
    assert 0 < cfg.batch_discount <= 1
    assert cfg.budget.monthly_cap_usd > 0
    assert cfg.weekly_runner.mode in {"claude_headless", "api"}
    assert cfg.track_a_runner.mode in {"claude_headless", "api"}


def test_quality_has_seven_checks() -> None:
    q = load_quality()
    assert set(q.checks) == {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"}
