"""Selection → headless runner → persistence, with the model replaced by a fake `run_cmd` (no network, no claude)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from macroweb.collect.fixtures import list_fixtures, read_fixture
from macroweb.collect.http import make_client
from macroweb.collect.pipeline import run_collect
from macroweb.config import load_extract, load_sources
from macroweb.db import repo
from macroweb.extract.runner import HeadlessExtractor
from macroweb.extract.select import select_candidates, theme_similarity

NOW = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)
SOURCES = ["fed_press", "yna_economy"]

FAKE_RESULT = {  # test double for the model output — shape of ExtractionResult, not a real-world fact
    "summary_ko": "테스트 요약. 두 번째 문장.",
    "claims": [
        {
            "text": "The committee kept the target range unchanged",
            "type": "event",
            "subject": "FOMC",
            "predicate": "kept",
            "object": "target range",
            "value": None,
            "unit": None,
            "time_ref": "2026-10-28",
            "cited_primary_doc": "FOMC statement 2026-10-28",
            "anonymous_source": False,
        },
        {
            "text": "Two members dissented",
            "type": "numeric",
            "subject": "FOMC",
            "predicate": "dissented",
            "object": None,
            "value": 2,
            "unit": "members",
            "time_ref": "2026-10-28",
            "cited_primary_doc": None,
            "anonymous_source": False,
        },
    ],
    "entities": [
        {"name": "FOMC", "type": "org", "role_hint": "committee"},
        {"name": "Kevin Warsh", "type": "person", "role_hint": "Fed Chair"},
    ],
    "relations": [{"src": "Kevin Warsh", "dst": "FOMC", "type": "reports_to", "sign": 0, "quote_span": None}],
    "cui_bono": [],
    "sentiment": {"market": 0.0, "policy_hawkish": 0.3},
    "novelty_hint": "update",
    "red_flags": [],
}


def _collect_fixtures() -> None:
    srcs = {s.id: s for s in load_sources().sources}
    table = {}
    for sid in SOURCES:
        fx, meta = list_fixtures(sid)[0]
        table[srcs[sid].url] = (read_fixture(fx), meta.get("content_type", "application/xml"))

    def handler(request: httpx.Request) -> httpx.Response:
        hit = table.get(str(request.url))
        return (
            httpx.Response(200, content=hit[0], headers={"content-type": hit[1]})
            if hit
            else httpx.Response(404)
        )

    with make_client(transport=httpx.MockTransport(handler)) as client:
        run_collect(
            "2026-11-02", source_ids=SOURCES, force=True, bodies=False, client=client, now=NOW, env={}
        )


def _fake_cmd(payload: dict | None, *, error: str | None = None, calls: list | None = None):
    def run(argv: list[str]) -> tuple[str, str, int]:
        if calls is not None:
            calls.append(argv)
        if error:
            return json.dumps({"type": "result", "is_error": True, "result": error}), "", 1
        return (
            json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "result": json.dumps(payload),
                    "structured_output": payload,
                    "usage": {
                        "input_tokens": 3000,
                        "output_tokens": 400,
                        "cache_read_input_tokens": 11000,
                        "cache_creation_input_tokens": 0,
                    },
                    "modelUsage": {"claude-haiku-5-5": {}},
                    "total_cost_usd": 0.004,
                    "duration_ms": 1500,
                }
            ),
            "",
            0,
        )

    return run


def test_selection_scores_and_marks_stories(tmp_path: Path) -> None:
    _collect_fixtures()
    conn = repo.connect()
    try:
        cands = select_candidates(
            conn, prompt_version=1, limit=25, now=datetime(2026, 11, 2, 2, 0, tzinfo=UTC)
        )
        assert cands, "expected candidates from fed_press / yna fixtures"
        tiers = [c.story.tier for c in cands]
        assert tiers == sorted(tiers), "T0 documents come first"
        assert all(0.0 <= c.impact <= 1.0 for c in cands)
        assert all(c.story.stratum in {"S-T0-STMT", "S-T1-KO"} for c in cands)
        marked = conn.execute(
            "SELECT COUNT(*) FROM story WHERE selected_at IS NOT NULL AND rep_article_id IS NOT NULL"
        ).fetchone()[0]
        assert marked == len(cands)
        sim, theme = theme_similarity(
            "연준 FOMC 점도표 인상 압박", [("fed", ["fomc", "점도표", "인상", "fed"])]
        )
        assert sim >= 0.75 and theme == "fed"
    finally:
        conn.close()


def test_runner_persists_claims_and_is_idempotent(tmp_path: Path) -> None:
    _collect_fixtures()
    conn = repo.connect()
    try:
        ecfg = load_extract()
        cands = [
            c
            for c in select_candidates(conn, prompt_version=ecfg.prompt.version, limit=40, now=NOW)
            if len(c.story.text) >= 60  # title-only items are left for the body fetcher, not the model
        ][:3]
        assert len(cands) == 3, "need three text-bearing candidates from the fixtures"
        calls: list = []
        ex = HeadlessExtractor(
            conn,
            extract_cfg=ecfg,
            run_cmd=_fake_cmd(FAKE_RESULT, calls=calls),
            now=NOW,
            limit_stamp=tmp_path / "limit.stamp",
        )
        report = ex.run(cands, max_calls=3)
        assert report.calls == 3 and report.succeeded == 3 and report.failed == 0, report.render()
        assert report.claims == 6 and report.tokens_in == 3 * 14000
        assert "--model" in calls[0] and calls[0][calls[0].index("--model") + 1] in {"haiku", "sonnet"}
        n_claims = conn.execute("SELECT COUNT(*) FROM claim").fetchone()[0]
        n_ev = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        n_ent = conn.execute("SELECT COUNT(*) FROM entity WHERE status='candidate'").fetchone()[0]
        assert n_claims == 6 and n_ev == 6 and n_ent >= 2
        warsh = conn.execute("SELECT id FROM entity WHERE canonical_name = 'Kevin Warsh'").fetchone()
        assert warsh and warsh["id"] == "kevin-warsh"  # resolved through config/aliases.yaml
        row = conn.execute("SELECT extracted_by, stratum, label, status FROM claim LIMIT 1").fetchone()
        assert (
            row["extracted_by"] == f"claude-haiku-5-5@{ex.prompt.version_tag}"
            and row["stratum"]
            and row["label"] is None
            and row["status"] == "active"
        )
        assert conn.execute("SELECT COUNT(*) FROM extraction WHERE status='succeeded'").fetchone()[0] == 3
        assert ex.calls_today() == 3
        # second pass: already-extracted stories are not selected again; persisting again would not duplicate
        again = select_candidates(conn, prompt_version=ecfg.prompt.version, limit=50, now=NOW)
        assert {c.story.story_id for c in again}.isdisjoint({c.story.story_id for c in cands})
        ex.run(cands[:1], max_calls=1)  # same story forced through again → same claim ids, no duplicates
        assert conn.execute("SELECT COUNT(*) FROM claim").fetchone()[0] == 6
    finally:
        conn.close()


def test_runner_limit_guard_and_schema_escalation(tmp_path: Path) -> None:
    _collect_fixtures()
    conn = repo.connect()
    try:
        ecfg = load_extract()
        cands = [
            c
            for c in select_candidates(conn, prompt_version=ecfg.prompt.version, limit=40, now=NOW)
            if len(c.story.text) >= 60
        ]
        stamp = tmp_path / "limit.stamp"
        limited = HeadlessExtractor(
            conn,
            extract_cfg=ecfg,
            run_cmd=_fake_cmd(None, error="You've hit your usage limit"),
            now=NOW,
            limit_stamp=stamp,
        )
        rep = limited.run(cands[:4], max_calls=4)
        assert (
            rep.limit_hit
            and rep.calls == 1
            and stamp.exists()
            and rep.stopped_reason == "subscription limit hit"
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM extraction WHERE status='failed' AND error='limit'"
            ).fetchone()[0]
            == 1
        )
        blocked = HeadlessExtractor(
            conn, extract_cfg=ecfg, run_cmd=_fake_cmd(FAKE_RESULT), now=NOW, limit_stamp=stamp
        )
        rep2 = blocked.run(cands[:4], max_calls=4)
        assert rep2.calls == 0 and "backoff" in (rep2.stopped_reason or "")
        stamp.unlink()
        # invalid schema from the small tier twice → escalation to the next tier, which succeeds
        seen: list[str] = []

        def flaky(argv: list[str]) -> tuple[str, str, int]:
            model = argv[argv.index("--model") + 1]
            seen.append(model)
            if model == "haiku":
                bad = {"summary_ko": "x"}  # missing required fields
                return (
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": False,
                            "result": json.dumps(bad),
                            "structured_output": bad,
                            "usage": {},
                            "modelUsage": {"claude-haiku-5-5": {}},
                        }
                    ),
                    "",
                    0,
                )
            return _fake_cmd(FAKE_RESULT)(argv)

        t1 = [c for c in cands if c.story.tier == 1][:1]
        assert t1, "need a T1 story for the escalation test"
        esc = HeadlessExtractor(conn, extract_cfg=ecfg, run_cmd=flaky, now=NOW, limit_stamp=stamp)
        rep3 = esc.run(t1, max_calls=5)
        assert seen[:2] == ["haiku", "haiku"] and seen[2] == "sonnet"
        assert rep3.escalated == 1 and rep3.succeeded == 1 and rep3.failed == 1
        rows = conn.execute(
            "SELECT model_tier, status, escalation_reason FROM extraction WHERE story_id = ? ORDER BY model_tier",
            (t1[0].story.story_id,),
        ).fetchall()
        assert {(r["model_tier"], r["status"]) for r in rows} == {
            ("small", "escalated"),
            ("mid", "succeeded"),
        }
        assert any(r["escalation_reason"] == "schema_fail" for r in rows)
    finally:
        conn.close()


def _harness_error(subtype: str):
    def run(argv: list[str]) -> tuple[str, str, int]:
        return (
            json.dumps(
                {
                    "type": "result",
                    "subtype": subtype,
                    "is_error": True,
                    "result": "",
                    "usage": {"input_tokens": 2, "output_tokens": 4198, "cache_creation_input_tokens": 8675},
                    "modelUsage": {"claude-sonnet-5-5": {}},
                }
            ),
            "",
            1,
        )

    return run


def test_transient_failures_are_retried_after_cooldown_and_capped(tmp_path: Path) -> None:
    _collect_fixtures()
    conn = repo.connect()
    try:
        ecfg = load_extract()
        kw = dict(prompt_version=ecfg.prompt.version, limit=40, now=NOW)
        cands = [c for c in select_candidates(conn, **kw) if len(c.story.text) >= 60]
        one = cands[:1]
        sid = one[0].story.story_id
        stamp = tmp_path / "limit.stamp"
        # 1) a harness error (e.g. the API dropped the stream) is not a schema failure: no escalation, attempts=1
        ex = HeadlessExtractor(
            conn,
            extract_cfg=ecfg,
            run_cmd=_harness_error("error_during_execution"),
            now=NOW,
            limit_stamp=stamp,
        )
        rep = ex.run(one, max_calls=4)
        assert rep.calls == 2 and rep.failed == 1 and rep.escalated == 0
        row = conn.execute(
            "SELECT status, error, attempts FROM extraction WHERE story_id = ?", (sid,)
        ).fetchone()
        assert row["status"] == "failed" and row["error"].startswith("harness: error_during_execution")
        assert row["attempts"] == 1
        # 2) not re-selected inside the cooldown, re-selected after it
        assert sid not in {c.story.story_id for c in select_candidates(conn, **kw)}
        later = {**kw, "now": NOW + timedelta(minutes=31)}
        assert sid in {c.story.story_id for c in select_candidates(conn, **later)}
        # 3) second transient failure reaches RETRY_MAX_ATTEMPTS → no more automatic retries
        ex2 = HeadlessExtractor(
            conn,
            extract_cfg=ecfg,
            run_cmd=_harness_error("error_during_execution"),
            now=later["now"],
            limit_stamp=stamp,
        )
        ex2.run(one, max_calls=4)
        row = conn.execute("SELECT attempts FROM extraction WHERE story_id = ?", (sid,)).fetchone()
        assert row["attempts"] == 2
        much_later = {**kw, "now": NOW + timedelta(hours=5)}
        assert sid not in {c.story.story_id for c in select_candidates(conn, **much_later)}
        # 4) the operator can still force it (claim ids are content-addressed, so a re-run cannot duplicate)
        forced = select_candidates(conn, **much_later, only=[sid], force=True)
        assert [c.story.story_id for c in forced] == [sid]
        assert select_candidates(conn, **much_later, only=[sid]) == []
        # 5) structured-output exhaustion counts as a schema failure → escalation ladder applies
        two = [c for c in cands if c.story.tier == 1 and c.story.story_id != sid][:1]
        assert two, "need a T1 story"
        seen: list[str] = []

        def exhausted_then_ok(argv: list[str]) -> tuple[str, str, int]:
            model = argv[argv.index("--model") + 1]
            seen.append(model)
            if model == "haiku":
                return _harness_error("error_max_structured_output_retries")(argv)
            return _fake_cmd(FAKE_RESULT)(argv)

        ex3 = HeadlessExtractor(conn, extract_cfg=ecfg, run_cmd=exhausted_then_ok, now=NOW, limit_stamp=stamp)
        rep3 = ex3.run(two, max_calls=5)
        assert seen == ["haiku", "haiku", "sonnet"] and rep3.escalated == 1 and rep3.succeeded == 1
        small = conn.execute(
            "SELECT status, error FROM extraction WHERE story_id = ? AND model_tier = 'small'",
            (two[0].story.story_id,),
        ).fetchone()
        assert small["status"] == "escalated" and small["error"].startswith(
            "schema: error_max_structured_output_retries"
        )
    finally:
        conn.close()
