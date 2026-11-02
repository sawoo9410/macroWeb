import pytest

from macroweb.config import load_models
from macroweb.cost import estimate
from macroweb.llm.router import ModelRouter, Usage


def test_router_resolves_ids_and_escalates() -> None:
    r = ModelRouter(load_models())
    assert r.model_id("small").startswith("claude-")
    assert r.alias("mid") == "sonnet"
    assert r.escalate("small") == "mid"
    assert r.escalate("mid") == "large"
    assert r.escalate("large") is None
    assert r.tier_for_stratum("S-DATA") is None
    assert r.tier_for_stratum("S-T1") == "small"


def test_estimate_cost_uses_prices_and_batch_discount() -> None:
    cfg = load_models()
    r = ModelRouter(cfg)
    t = cfg.tiers["small"]
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert r.estimate_cost("small", usage) == pytest.approx(t.input + t.output)
    assert r.estimate_cost("small", usage, batch=True) == pytest.approx(
        (t.input + t.output) * cfg.batch_discount
    )


def test_monthly_estimate_under_cap() -> None:
    est = estimate()
    assert est.api_total_usd < est.cap_usd
    assert est.lines
    if est.weekly_runner_mode == "claude_headless" and est.track_a_runner_mode == "claude_headless":
        assert est.api_total_usd == 0  # everything rides on the Max subscription (ADR-0007)
        assert est.subscription_equivalent_usd > 0
        assert 50 < est.subscription_calls_per_day < 400 and est.subscription_tokens_per_day > 1e6
