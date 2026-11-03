"""Phase 6–7 v1: verify v2 signals and traps, Q3/Q5 quality checks, review decisions, verification notes, and the
monthly learning loop — on fixture stories with persisted test-double claims; no model calls, no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from test_verify_v1 import NOW, T0_RESULT, T1_RESULT, _collect_fixtures, _story_for

from macroweb.db import repo
from macroweb.extract.persist import persist_result
from macroweb.graph.analysis import iso_week
from macroweb.graph.store import load_seed, upsert_edge, upsert_entity
from macroweb.llm.schemas import ExtractionResult
from macroweb.monthly.run import month_bounds, run_monthly, update_credibility
from macroweb.quality.weekly import run_quality
from macroweb.verify.notes import verification_notes
from macroweb.verify.review import apply_review, parse_review_md
from macroweb.verify.run import run_verify, write_review_md
from macroweb.verify.signals_v2 import generated_content, market_reaction


def _claim(text: str, ctype: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "text": text,
        "type": ctype,
        "subject": None,
        "predicate": None,
        "object": None,
        "value": None,
        "unit": None,
        "time_ref": None,
        "cited_primary_doc": None,
        "anonymous_source": False,
    }
    base.update(kw)
    return base


def test_verify_v2_signals_traps_notes_and_review(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MACROWEB_REVIEW_DIR", str(tmp_path / "review"))
    _collect_fixtures()
    conn = repo.connect()
    try:
        t0 = _story_for(conn, "fed_press", tier=0, stratum="S-T0-STMT", impact=0.9)
        t1 = _story_for(conn, "yna_economy", tier=1, stratum="S-T1-KO", impact=0.95)
        pub = (t1.published_at or "")[:10]
        prev_day = (datetime.fromisoformat(pub) - timedelta(days=1)).date().isoformat()
        conn.executemany(
            "INSERT INTO market(date, key, value, source) VALUES (?, 'NAVER:KOSPI', ?, 'test')",
            [(prev_day, 2500.0), (pub, 2600.9)],
        )
        conn.commit()
        v2_result = {
            **T1_RESULT,
            "claims": [
                *T1_RESULT["claims"],
                _claim(
                    "코스피가 4% 급등했다",
                    "numeric",
                    subject="코스피",
                    predicate="급등",
                    value=4.0,
                    unit="%",
                    time_ref=pub,
                ),
                _claim("코스피가 급락했다", "event", subject="코스피", predicate="급락", time_ref=pub),
                _claim(
                    "외신 종합: 관세가 인상될 것이라고 소식통이 전했다",
                    "event",
                    subject="관세",
                    anonymous_source=True,
                ),
            ],
            "red_flags": ["'외신 종합' 원문 링크 없음"],
        }
        persist_result(
            conn, t0, ExtractionResult.model_validate(T0_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        persist_result(
            conn, t1, ExtractionResult.model_validate(v2_result), extracted_by="test@extract@v2", now=NOW
        )
        # a later article whose title carries a correction cue and names the subject → debunk candidate
        rep = conn.execute("SELECT * FROM article WHERE id = ?", (t1.extra["rep_article_id"],)).fetchone()
        later = (datetime.fromisoformat(rep["published_at"]) + timedelta(days=2)).isoformat()
        conn.execute(
            "INSERT INTO article(id, url, canonical_url, source_id, title, published_at, fetched_at, lang, status) VALUES ('c0rr000000000001', ?, ?, ?, ?, ?, ?, 'ko', 'new')",
            (
                rep["url"] + "?c=1",
                rep["canonical_url"] + "?c=1",
                rep["source_id"],
                "코스피 급락 보도는 사실무근… 거래소 해명",
                later,
                later,
            ),
        )
        conn.commit()
        report = run_verify(conn, now=NOW, day="2026-11-02")
        up = conn.execute(
            "SELECT signals_json, label FROM claim WHERE text = '코스피가 4% 급등했다'"
        ).fetchone()
        v = json.loads(up["signals_json"])["verify"]
        assert (
            v["v2"]["market_reaction"]["verdict"] == "consistent"
            and v["v2"]["market_reaction"]["key"] == "NAVER:KOSPI"
        )
        down = json.loads(
            conn.execute("SELECT signals_json FROM claim WHERE text = '코스피가 급락했다'").fetchone()[
                "signals_json"
            ]
        )["verify"]
        assert down["v2"]["market_reaction"]["verdict"] == "contradicted"
        assert down["v2"]["correction"]["candidates"] and report.debunk_candidates >= 1
        roundup = json.loads(
            conn.execute("SELECT signals_json FROM claim WHERE text LIKE '외신 종합%'").fetchone()[
                "signals_json"
            ]
        )["verify"]
        assert {"korean_foreign_roundup", "anonymous_policy_rumor"} <= set(
            roundup["v2"]["traps"]
        ) and roundup["n_independent"] == 1
        assert roundup["v2"]["domain"] == {
            "note": "registration age / typosquat need WHOIS (not implemented)"
        }
        assert (
            conn.execute("SELECT COUNT(*) FROM review_queue WHERE kind = 'debunk_candidate'").fetchone()[0]
            >= 1  # every 코스피 claim of the story shares the subject named in the correction title
        )
        # #11: the same sentence from three sources within a day
        row = conn.execute("SELECT * FROM claim WHERE text = '코스피가 2,600.5에 마감했다'").fetchone()
        for i, src in enumerate(("mk_economy", "hankyung_economy")):
            conn.execute(
                "INSERT INTO claim(id, story_id, text, type, first_seen, last_updated, status, signals_json) VALUES (?, ?, ?, 'numeric', ?, ?, 'active', ?)",
                (
                    f"dup000000000000{i}",
                    t1.story_id,
                    row["text"],
                    NOW.isoformat(),
                    NOW.isoformat(),
                    json.dumps({"source_id": src}),
                ),
            )
        conn.commit()
        gen = generated_content(conn, row)
        assert gen["flag"] and gen["n_domains"] == 3
        assert (
            market_reaction(
                conn, row, rep, __import__("macroweb.config", fromlist=["load_verify"]).load_verify()
            )[0]
            is None
        )
        # verification notes name the signal
        notes = verification_notes(conn, iso_week(NOW.date()))
        assert "검증 불가" in notes and "라벨 분포" in notes
        # human decisions flow back
        md = write_review_md(conn, "2026-11-02")
        text = md.read_text(encoding="utf-8")
        cid = conn.execute(
            "SELECT claim_id FROM review_queue WHERE kind = 'low_conf_high_impact' AND decided_at IS NULL LIMIT 1"
        ).fetchone()
        assert cid is not None
        filled = "\n".join(
            ln.replace("|  |", "| reject |") if f"`{cid['claim_id']}`" in ln else ln
            for ln in text.splitlines()
        )
        assert parse_review_md(filled) and parse_review_md(filled)[0][1] == "reject"
        md.write_text(filled, encoding="utf-8")
        res = apply_review(conn, md, by="test", decisions_file=tmp_path / "decisions.jsonl")
        assert (
            res.applied >= 1
            and res.by_decision.get("reject", 0) >= 1
            and (tmp_path / "decisions.jsonl").exists()
        )
        assert (
            conn.execute("SELECT n_refuted FROM source_stats WHERE source_id = 'yna_economy'").fetchone()[0]
            >= 1
        )
        assert (
            apply_review(conn, md, by="test", decisions_file=tmp_path / "decisions.jsonl").applied == 0
        )  # idempotent
    finally:
        conn.close()


def test_quality_q3_q5_and_monthly_loop(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MACROWEB_REVIEW_DIR", str(tmp_path / "review"))
    _collect_fixtures()
    conn = repo.connect()
    try:
        load_seed(conn, now=datetime(2026, 10, 1, tzinfo=UTC))
        t0 = _story_for(conn, "fed_press", tier=0, stratum="S-T0-STMT", impact=0.9)
        t1 = _story_for(conn, "yna_economy", tier=1, stratum="S-T1-KO", impact=0.95)
        persist_result(
            conn, t0, ExtractionResult.model_validate(T0_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        persist_result(
            conn, t1, ExtractionResult.model_validate(T1_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        run_verify(conn, now=NOW, day="2026-11-02", write_md=False)
        # Q3: two VERIFIED claims, same subject/predicate/month, different values; opposite-sign edges
        for i, val in enumerate((3.75, 4.0)):
            conn.execute(
                """INSERT INTO claim(id, story_id, text, type, subject_eid, predicate, value, unit, time_ref, label, confidence, impact, first_seen, last_updated, status, signals_json)
                   VALUES (?, ?, ?, 'numeric', 'fed', 'target range upper bound', ?, '%', '2026-10-29', 'VERIFIED', 0.9, 0.8, ?, ?, 'active', '{"source_id":"fed_press"}')""",
                (
                    f"q3c0000000000{i:03d}",
                    t0.story_id,
                    f"upper bound {val}",
                    val,
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            )
        for i in range(
            2
        ):  # evidence keeps them active through Q1 (an evidence-less claim is quarantined first)
            conn.execute(
                "INSERT INTO evidence(id, claim_id, article_id, kind) VALUES (?, ?, ?, 'primary_doc')",
                (f"evq3c00000000{i:03d}", f"q3c0000000000{i:03d}", t0.extra["rep_article_id"]),
            )
        upsert_entity(conn, eid="x1", etype="org", name="X1")
        upsert_entity(conn, eid="y1", etype="org", name="Y1")
        for sign in (1, -1):
            upsert_edge(
                conn,
                src="x1",
                dst="y1",
                rtype="benefits_from" if sign > 0 else "hurt_by",
                sign=sign,
                weight=0.8,
                confidence=0.9,
                evidence_ids=["q3c0000000000000"],
                origin="extracted",
                story_id=t0.story_id,
                seen_at=NOW.isoformat(),
            )
        # same type opposite signs: force a second row of the same type by direct insert
        conn.execute(
            "INSERT INTO relation(id, src_eid, dst_eid, type, sign, weight, confidence, valid_from, evidence_ids, origin, status) VALUES ('edgeneg000000001', 'x1', 'y1', 'benefits_from', -1, 0.8, 0.9, ?, '[\"q3c0000000000001\"]', 'extracted', 'candidate')",
            (NOW.isoformat(),),
        )
        # Q5: a published report cited a claim that later got superseded
        cited = conn.execute("SELECT id FROM claim WHERE story_id = ? LIMIT 1", (t1.story_id,)).fetchone()[
            "id"
        ]
        conn.execute(
            "INSERT INTO report_citation(report_week, claim_id, section) VALUES ('2026-W44', ?, 'body')",
            (cited,),
        )
        conn.execute("UPDATE claim SET status = 'superseded' WHERE id = ?", (cited,))
        conn.commit()
        week = iso_week(NOW.date())
        res = run_quality(conn, week, now=NOW, reports_dir=tmp_path / "quality")
        assert (
            res.q3["claim_pairs"] >= 1
            and res.q3["edge_pairs"] >= 1
            and res.q3["queued"] >= 2
            and res.lights["Q3"] == "green"
        )
        assert res.q5["count"] >= 1 and res.lights["Q5"] == "yellow" and "정정" in res.scoreline()
        late = run_quality(conn, week, now=NOW + timedelta(days=8), reports_dir=tmp_path / "quality")
        assert late.lights["Q3"] == "yellow" and late.q3["queued"] == 0
        row = conn.execute("SELECT q3_open, q5_errata FROM quality_run WHERE week = ?", (week,)).fetchone()
        assert row["q3_open"] >= 2 and row["q5_errata"] >= 1

        # monthly loop
        start, end = month_bounds("2026-11")
        assert start == "2026-11-01T00:00:00+00:00" and end == "2026-12-01T00:00:00+00:00"
        before = conn.execute(
            "SELECT credibility FROM source_stats WHERE source_id = 'fed_press'"
        ).fetchone()["credibility"]
        upd = update_credibility(conn, start, end, now_iso=NOW.isoformat())
        fed = next(u for u in upd if u["source"] == "fed_press")
        assert fed["confirmed"] >= 1 and fed["credibility"] >= before - 1e-9 and fed["credibility"] <= 0.99
        m = run_monthly(
            conn,
            "2026-11",
            now=NOW + timedelta(days=30),
            reports_dir=tmp_path / "monthly",
            digest_dir=tmp_path / "digests",
        )
        assert m.report and m.report.exists() and m.macro_background and m.macro_background.exists()
        text = m.macro_background.read_text(encoding="utf-8")
        assert text.count("\n") >= 10 and "[F]" in text and "구독" in text
        retro = m.report.read_text(encoding="utf-8")
        assert "출처 신뢰도" in retro and "미해결" in retro and "검증기 재학습" in retro
        assert m.cost["billing"].startswith("Claude Max") and isinstance(m.graph["hubs"], list)
    finally:
        conn.close()
