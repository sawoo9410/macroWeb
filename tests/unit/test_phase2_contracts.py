"""Phase 2 interfaces (ADR-0006): schema v3, verify/extract configs, score & label rules, custom ids, prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from macroweb.config import load_extract, load_verify
from macroweb.db import repo
from macroweb.extract.contracts import ExtractionRequest, StoryInput, make_custom_id, parse_custom_id
from macroweb.llm.prompting import build_extraction_messages, load_prompt, truncate_body
from macroweb.verify.contracts import Label, SignalVector, decide_label, needs_review, report_use, score


def test_migration_0003_applies(tmp_path: Path) -> None:
    info = repo.init_db(tmp_path / "t.sqlite")
    assert info["schema_version"] == 3
    assert "0003_phase2.sql" in info["applied_migrations"]
    for t in ("llm_batch", "extraction", "review_queue"):
        assert t in info["tables"], t
    conn = repo.connect(tmp_path / "t.sqlite")
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(story)").fetchall()}
        assert {"stratum", "lang", "rep_article_id", "impact", "selected_at"} <= cols
    finally:
        conn.close()


def test_verify_and_extract_configs_load() -> None:
    v = load_verify()
    assert v.weights.bias < 0 and v.weights.debunked < 0 < v.weights.primary_match
    assert set(v.labels.order) == {label.value for label in Label}
    e = load_extract()
    assert e.daily_story_cap == 80 and e.max_input_tokens == 6000
    assert e.batch.last_submit_kst < e.batch.realtime_cutoff_kst
    assert e.headless.calls_per_tick <= e.headless.max_calls_per_day and e.headless.max_turns == 1
    assert e.headless.model_flag_by_tier["small"] == "haiku"


def test_score_ordering_matches_plan_intuition() -> None:
    t0_primary = SignalVector(prior=0.95, n_independent=1, primary_match=1.0)
    t1_two_sources = SignalVector(prior=0.80, n_independent=2)
    t1_single = SignalVector(prior=0.80, n_independent=1)
    t4_rumor = SignalVector(prior=0.30, n_independent=1, rumor_stale=1.0, language_risk=0.6)
    debunked = SignalVector(prior=0.80, n_independent=3, debunked=1.0)
    s = [score(v) for v in (t0_primary, t1_two_sources, t1_single, t4_rumor, debunked)]
    assert s[0] > 0.85
    assert s[0] > s[1] > s[2] > s[3]
    assert s[3] < 0.5
    assert s[4] < s[2]
    assert "primary_match" in t1_single.missing and "prior" not in t1_single.missing


def test_label_rules_in_plan_order() -> None:
    assert decide_label(SignalVector(spam_satire=True, primary_match=1.0)) is Label.SPAM_SATIRE
    assert decide_label(SignalVector(debunked=1.0, primary_match=1.0)) is Label.DEBUNKED
    assert decide_label(SignalVector(recycled=1.0, n_independent=4)) is Label.RECYCLED
    assert decide_label(SignalVector(primary_match=1.0)) is Label.VERIFIED
    assert decide_label(SignalVector(numeric_match=1.0)) is Label.VERIFIED
    assert decide_label(SignalVector(numeric_match=-1.0, n_independent=3)) is Label.DISPUTED
    assert decide_label(SignalVector(disputed=True, n_independent=3)) is Label.DISPUTED
    assert decide_label(SignalVector(n_independent=2)) is Label.CORROBORATED
    assert decide_label(SignalVector(n_independent=1, unverifiable=True)) is Label.UNVERIFIABLE
    assert decide_label(SignalVector(n_independent=1, rumor_stale=1.0)) is Label.UNVERIFIABLE
    assert decide_label(SignalVector(n_independent=1)) is Label.SINGLE_SOURCE
    assert report_use(Label.VERIFIED) == "F" and report_use(Label.DEBUNKED) == "notes_only"
    assert needs_review(0.8, 0.4) and not needs_review(0.8, 0.6) and not needs_review(0.3, 0.1)


def test_custom_id_roundtrip_and_limits() -> None:
    req = ExtractionRequest(
        story_id="st-0123456789abcdef", prompt_version=1, model_tier="small", stratum="S-T1"
    )
    cid = req.custom_id()
    assert cid == "ext_st-0123456789abcdef_v1_small" and len(cid) <= 64
    assert parse_custom_id(cid) == ("st-0123456789abcdef", 1, "small")
    with pytest.raises(ValueError):
        make_custom_id("ext", "bad id with spaces", 1, "small")
    with pytest.raises(ValueError):
        parse_custom_id("something-else")


def test_prompt_loading_and_message_assembly() -> None:
    spec = load_prompt("extract", 1)
    assert spec.version_tag == "extract@v1" and "claim" in spec.system
    long_text = "연준이 금리를 동결했다. " * 2000
    body, truncated = truncate_body(long_text, 6000)
    assert truncated and "중략" in body and len(body) < len(long_text)
    story = StoryInput(
        story_id="st-abc",
        source_id="fed_press",
        tier=0,
        stratum="S-T0-STMT",
        title="FOMC statement",
        text="The Committee decided to maintain the target range.",
        url="https://www.federalreserve.gov/x",
        published_at="2026-10-28",
        lang="en",
    )
    system, user = build_extraction_messages(story, spec, 6000)
    assert system == spec.system
    for needle in (
        "source_id: fed_press",
        "tier: T0",
        "stratum: S-T0-STMT",
        "truncated: no",
        "## 본문",
        "maintain the target range",
    ):
        assert needle in user
    with pytest.raises(ValueError):
        load_prompt("extract", 99)
