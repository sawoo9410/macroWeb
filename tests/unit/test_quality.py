"""Weekly quality review v1 (Q1·Q2·Q4·Q6) on fixture-derived data: quarantine, expiry, supersession,
alias merge, coverage baseline, scorecard file and quality_run row."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from test_verify_v1 import NOW, T0_RESULT, T1_RESULT, _collect_fixtures, _story_for

from macroweb.db import repo
from macroweb.extract.persist import persist_result
from macroweb.graph.analysis import iso_week
from macroweb.graph.store import load_seed, relation_id, upsert_edge, upsert_entity
from macroweb.llm.schemas import ExtractionResult
from macroweb.quality.weekly import run_quality
from macroweb.verify.run import run_verify


def test_quality_v1_checks_and_scorecard(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MACROWEB_REVIEW_DIR", str(tmp_path / "review"))
    _collect_fixtures()
    conn = repo.connect()
    try:
        load_seed(conn, now=NOW)
        t0 = _story_for(conn, "fed_press", tier=0, stratum="S-T0-STMT", impact=0.9)
        t1 = _story_for(conn, "yna_economy", tier=1, stratum="S-T1-KO", impact=0.95)
        forecast = {
            **T1_RESULT,
            "claims": [
                *T1_RESULT["claims"],
                {
                    "text": "연내 기준금리가 인하될 것으로 전망된다",
                    "type": "forecast",
                    "subject": "한국은행",
                    "predicate": "인하 전망",
                    "object": None,
                    "value": None,
                    "unit": None,
                    "time_ref": "2026-10",
                    "cited_primary_doc": None,
                    "anonymous_source": False,
                },
                {
                    "text": "한국은행이 기준금리를 2.75%로 결정했다",
                    "type": "numeric",
                    "subject": "한국은행",
                    "predicate": "기준금리 결정",
                    "object": None,
                    "value": 2.75,
                    "unit": "%",
                    "time_ref": "2026-10-23",
                    "cited_primary_doc": None,
                    "anonymous_source": False,
                },
            ],
        }
        persist_result(
            conn, t0, ExtractionResult.model_validate(T0_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        persist_result(
            conn, t1, ExtractionResult.model_validate(forecast), extracted_by="test@extract@v2", now=NOW
        )
        # an older "current state" claim with the same subject+predicate but a different value → superseded
        conn.execute(
            """INSERT INTO claim(id, story_id, text, type, subject_eid, predicate, value, unit, time_ref, first_seen, last_updated, status, stratum)
               VALUES ('0ld0000000000001', ?, '한국은행이 기준금리를 2.50%로 결정했다', 'numeric', 'bank-of-korea', '기준금리 결정', 2.5, '%', '2026-08-28', ?, ?, 'active', 'S-T1-KO')""",
            (t1.story_id, (NOW - timedelta(days=60)).isoformat(), (NOW - timedelta(days=60)).isoformat()),
        )
        conn.execute(
            "INSERT INTO evidence(id, claim_id, article_id, kind) VALUES ('ev0ld00000000001', '0ld0000000000001', ?, 'supports')",
            (t1.extra["rep_article_id"],),
        )
        # an extracted edge without evidence (must never exist) and a claim whose article is gone
        upsert_entity(conn, eid="x-org", etype="org", name="X Org")
        upsert_edge(
            conn,
            src="x-org",
            dst="fed",
            rtype="pressures",
            sign=-1,
            weight=0.5,
            confidence=0.5,
            evidence_ids=[],
            origin="extracted",
            story_id="st-none",
            seen_at=NOW.isoformat(),
        )
        conn.execute(
            """INSERT INTO claim(id, story_id, text, type, first_seen, last_updated, status)
               VALUES ('0rphan0000000001', ?, 'orphan claim without any article', 'event', ?, ?, 'active')""",
            (t1.story_id, NOW.isoformat(), NOW.isoformat()),
        )
        # alias duplicate for Q4
        upsert_entity(conn, eid="bok-dup", etype="org", name="Bank of Korea")
        conn.commit()
        run_verify(conn, now=NOW, day="2026-11-02", write_md=False)

        week = iso_week(NOW.date())
        res = run_quality(conn, week, now=NOW, reports_dir=tmp_path / "quality")
        assert res.q1["fail"] >= 2 and res.q1["quarantined_edges"] == 1 and res.q1["quarantined_claims"] == 1
        assert res.q1["seed_pending"] >= 15 and res.lights["Q1"] == "red"
        assert (
            conn.execute(
                "SELECT status FROM relation WHERE id = ?", (relation_id("x-org", "fed", "pressures"),)
            ).fetchone()["status"]
            == "quarantined"
        )
        assert (
            conn.execute("SELECT status FROM claim WHERE id = '0rphan0000000001'").fetchone()["status"]
            == "quarantined"
        )
        assert res.q2["expired_claims"] == 1 and res.q2["superseded"] == 1
        old = conn.execute("SELECT status, superseded_by FROM claim WHERE id = '0ld0000000000001'").fetchone()
        assert old["status"] == "superseded" and old["superseded_by"]
        assert ("bok-dup", "bank-of-korea") in [tuple(m.split("→")) for m in res.q4["merged"]]
        assert (
            res.q6["history_weeks"] < 2
            and "baseline" in res.q6["note"]
            and res.lights["Q6"] in ("green", "yellow")
        )
        assert res.report and res.report.exists()
        text = res.report.read_text(encoding="utf-8")
        assert "데이터 품질:" in text and "Q1🔴" in text and "Phase 6" in text
        row = conn.execute("SELECT * FROM quality_run WHERE week = ?", (week,)).fetchone()
        assert row["q1_fail"] == res.q1["fail"] and json.loads(row["status_json"])["lights"]["Q1"] == "red"
        # second run: nothing new to quarantine, same scorecard shape
        res2 = run_quality(conn, week, now=NOW, reports_dir=tmp_path / "quality")
        assert res2.q1["quarantined_edges"] == 0 and res2.q2["superseded"] == 0
    finally:
        conn.close()
