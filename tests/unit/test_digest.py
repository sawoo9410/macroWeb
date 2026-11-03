"""Daily digest: every placeholder filled from the DB/config, unimplemented engines named as such."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_verify_v1 import NOW, T0_RESULT, T1_RESULT, _collect_fixtures, _story_for

from macroweb.db import repo
from macroweb.digest.daily import build_digest, kst_day_bounds, upcoming_events, write_digest
from macroweb.extract.persist import persist_result
from macroweb.llm.schemas import ExtractionResult
from macroweb.verify.run import run_verify


def test_kst_day_bounds_are_utc() -> None:
    start, end = kst_day_bounds("2026-11-02")
    assert start == "2026-11-01T15:00:00+00:00" and end == "2026-11-02T15:00:00+00:00"


def test_upcoming_events_reads_calendar() -> None:
    text = upcoming_events("2026-11-30")
    assert (
        "FOMC" in text and "2026-12-09" in text
    )  # confirmed from the fomc_calendar fixture (config/calendar.yaml)
    assert "TBD" not in text


def test_digest_is_filled_from_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MACROWEB_REVIEW_DIR", str(tmp_path / "review"))
    _collect_fixtures()
    conn = repo.connect()
    try:
        t0 = _story_for(conn, "fed_press", tier=0, stratum="S-T0-STMT", impact=0.9)
        t1 = _story_for(conn, "yna_economy", tier=1, stratum="S-T1-KO", impact=0.95)
        persist_result(
            conn, t0, ExtractionResult.model_validate(T0_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        persist_result(
            conn, t1, ExtractionResult.model_validate(T1_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        run_verify(conn, now=NOW, day="2026-11-02")
        data = build_digest(conn, "2026-11-02")
        v = data.values
        assert v["claim_1_id"] != "-" and v["claim_1_label"].startswith("VERIFIED")
        assert v["claim_1"].startswith("[F] ")
        # the fixture statement predates the digest day, so it counts as "read today" (claims), not "new today"
        assert v["n_t0"].isdigit() and "fed_press" in v["t0_docs"] and "claim 1" in v["t0_docs"]
        assert (
            int(v["n_review"]) == 1 and v["n_stories"].isdigit() and v["n_articles"].isdigit()
        )  # fixture stories predate the day; counts are still rendered
        assert "Phase 3" in v["regime_line"] and "Phase 3" in v["market_consistency"]
        path = write_digest(conn, "2026-11-02")
        text = path.read_text(encoding="utf-8")
        assert path.name == "2026-11-02.md" and "{{" not in text and "}}" not in text
        assert "review/2026-11-02.md" in text and data.values["claim_1_id"] in text
        # idempotent rewrite
        assert write_digest(conn, "2026-11-02").read_text(encoding="utf-8") == text
    finally:
        conn.close()
