"""Graph v1: seed load, extracted relations → edges with evidence, resolution/merge, expiry, propagation,
paths, weekly diff, statistical-edge calculator, vault/HTML/PNG export. Fixture stories + persisted claims
(no model); the extraction result with relations is a test double shaped like ExtractionResult."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from test_verify_v1 import NOW, T0_RESULT, T1_RESULT, _collect_fixtures, _story_for

from macroweb.db import repo
from macroweb.extract.persist import persist_result
from macroweb.graph.analysis import (
    hubs,
    iso_week,
    k_paths,
    pair_stats,
    pearson,
    propagate,
    week_bounds,
    weekly_diff,
)
from macroweb.graph.export import export_vault, render_html, render_png
from macroweb.graph.store import (
    active_edges,
    edge_family,
    expire_edges,
    graph_counts,
    load_seed,
    relation_id,
    resolve_entities,
    update_from_extractions,
    upsert_edge,
    upsert_entity,
)
from macroweb.llm.schemas import ExtractionResult
from macroweb.verify.run import run_verify

T1_WITH_RELATIONS = {
    **T1_RESULT,
    "entities": [
        {"name": "Kevin Warsh", "type": "person", "role_hint": "Fed Chair"},
        {"name": "FOMC", "type": "org", "role_hint": None},
        {"name": "코스피", "type": "asset", "role_hint": None},
    ],
    "relations": [
        {"src": "Kevin Warsh", "dst": "FOMC", "type": "reports_to", "sign": 0, "quote_span": None},
        {"src": "외국인", "dst": "코스피", "type": "hurts", "sign": -1, "quote_span": "외국인 순매도"},
        {
            "src": "코스피",
            "dst": "코스피",
            "type": "competes_with",
            "sign": 0,
            "quote_span": None,
        },  # self-loop → skipped
    ],
}


def _insert_extraction(conn, story_id: str, result: dict, tier: str = "small") -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        """INSERT OR REPLACE INTO extraction(story_id, prompt_version, model_tier, custom_id, status, result_json, created_at, updated_at)
           VALUES (?, '2', ?, ?, 'succeeded', ?, ?, ?)""",
        (
            story_id,
            tier,
            f"t_{story_id}_{tier}",
            json.dumps(result, ensure_ascii=False),
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    conn.commit()


def test_edge_family_and_ids() -> None:
    assert edge_family("supplies_to") == "structural" and edge_family("pressures") == "power_interest"
    assert edge_family("predicts") == "discourse" and edge_family("correlates_with") == "other"
    assert relation_id("a", "b", "x") == relation_id("a", "b", "x") != relation_id("b", "a", "x")


def test_pearson_and_pair_stats_without_history() -> None:
    xs = [float(i) for i in range(20)]
    ys = [2 * x + 1 for x in xs]
    assert math.isclose(pearson(xs, ys) or 0, 1.0)
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    repo.init_db()
    conn = repo.connect()
    try:
        ps = pair_stats(conn, "UST:10Y", "NAVER:.SOX")
        assert ps.r is None and "no market data" in ps.note
        for i in range(10):  # a handful of points is still "insufficient history", never a fabricated r
            d = (NOW.date() - timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT INTO market(date, key, value, source) VALUES (?, 'UST:10Y', ?, 'test')",
                (d, 4.0 + i * 0.01),
            )
            conn.execute(
                "INSERT INTO market(date, key, value, source) VALUES (?, 'NAVER:.SOX', ?, 'test')",
                (d, 5000 - i * 10),
            )
        conn.commit()
        ps = pair_stats(conn, "UST:10Y", "NAVER:.SOX")
        assert ps.r is None and "insufficient history" in ps.note
    finally:
        conn.close()


def test_seed_edges_resolution_propagation_and_exports(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MACROWEB_REVIEW_DIR", str(tmp_path / "review"))
    _collect_fixtures()
    conn = repo.connect()
    try:
        rep = load_seed(conn, now=NOW)
        assert rep.entities_seen >= 20 and rep.edges_seen >= 17 and rep.persons >= 1 and not rep.problems
        assert load_seed(conn, now=NOW).edges_new == 0  # idempotent
        counts = graph_counts(conn)
        assert counts["entity_candidate"] >= 20 and counts["edge_candidate"] >= 17
        assert counts["edge_without_evidence"] >= 17  # seed edges wait for claims (Q1 reports them)

        # extracted relations → edges with the story's claims as evidence
        t0 = _story_for(conn, "fed_press", tier=0, stratum="S-T0-STMT", impact=0.9)
        t1 = _story_for(conn, "yna_economy", tier=1, stratum="S-T1-KO", impact=0.95)
        persist_result(
            conn, t0, ExtractionResult.model_validate(T0_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        persist_result(
            conn,
            t1,
            ExtractionResult.model_validate(T1_WITH_RELATIONS),
            extracted_by="test@extract@v2",
            now=NOW,
        )
        run_verify(conn, now=NOW, day="2026-11-02", write_md=False)
        _insert_extraction(conn, t1.story_id, T1_WITH_RELATIONS)
        st = update_from_extractions(conn, now=NOW)
        assert st.inserted == 1 and st.reinforced == 1 and st.skipped_unresolved == 1, st
        warsh_fed = conn.execute(
            "SELECT * FROM relation WHERE id = ?", (relation_id("kevin-warsh", "fed", "reports_to"),)
        ).fetchone()
        assert warsh_fed["origin"] == "seed" and warsh_fed["n_stories"] == 1
        assert len(json.loads(warsh_fed["evidence_ids"])) == len(
            T1_RESULT["claims"]
        )  # seed edge now carries evidence
        hurt = conn.execute("SELECT * FROM relation WHERE type = 'hurt_by' AND dst_eid = 'kospi'").fetchone()
        assert (
            hurt is not None
            and hurt["sign"] == -1
            and hurt["weight"] == 0.5
            and hurt["status"] == "candidate"
        )
        assert (
            conn.execute("SELECT type, status FROM entity WHERE id = '외국인'").fetchone()["status"]
            == "candidate"
        )
        assert update_from_extractions(conn, now=NOW).inserted == 0  # idempotent

        # resolution: alias duplicate folds into the canonical id, claims follow
        upsert_entity(conn, eid="federal-reserve-x", etype="org", name="Federal Reserve")
        conn.execute(
            "UPDATE claim SET subject_eid = 'federal-reserve-x' WHERE id = (SELECT id FROM claim LIMIT 1)"
        )
        conn.commit()
        rr = resolve_entities(conn, now=NOW)
        assert ("federal-reserve-x", "fed") in rr.merged
        assert (
            conn.execute("SELECT status, merged_into FROM entity WHERE id = 'federal-reserve-x'").fetchone()[
                "merged_into"
            ]
            == "fed"
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM claim WHERE subject_eid = 'federal-reserve-x'").fetchone()[0]
            == 0
        )

        # expiry by family
        old = (NOW - timedelta(days=100)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE relation SET last_reinforced = ?, valid_from = ? WHERE id = ?",
            (old, old, relation_id("donald-trump", "fed", "pressures")),
        )
        conn.execute(
            "UPDATE relation SET last_reinforced = ?, valid_from = ? WHERE id = ?",
            (old, old, relation_id("nvidia", "sk-hynix", "customer_of")),
        )
        conn.commit()
        assert expire_edges(conn, now=NOW) == 1
        assert (
            conn.execute(
                "SELECT status FROM relation WHERE id = ?", (relation_id("donald-trump", "fed", "pressures"),)
            ).fetchone()["status"]
            == "expired"
        )
        assert (
            conn.execute(
                "SELECT status FROM relation WHERE id = ?",
                (relation_id("nvidia", "sk-hynix", "customer_of"),),
            ).fetchone()["status"]
            == "candidate"
        )

        # propagation follows impact edges with decay and sign flips; expired edges are gone
        edges = active_edges(conn, as_of=NOW.date().isoformat())
        assert all(e["status"] in ("candidate", "confirmed") for e in edges)
        effects = propagate(edges, "fomc-2026-12-09", sign=1, magnitude=1.0, floor=0.01)
        targets = {(e.target, e.depth): e for e in effects}
        assert ("ust10y", 1) in targets and targets[("ust10y", 1)].sign == 1
        assert ("sox", 2) in targets and targets[("sox", 2)].sign == -1  # UST10Y −→ SOX
        assert targets[("sox", 2)].magnitude < targets[("ust10y", 1)].magnitude
        assert propagate(edges, "fomc-2026-12-09", floor=0.5) == []
        paths = k_paths(edges, "fomc-2026-12-09", "sk-hynix", k=3)
        assert paths and paths[0]["nodes"][0] == "fomc-2026-12-09" and paths[0]["nodes"][-1] == "sk-hynix"
        assert hubs(edges, top=3)

        # weekly diff + snapshot
        week = iso_week(NOW.date())
        start, end = week_bounds(week)
        assert start <= NOW.isoformat() < end
        d = weekly_diff(conn, week)
        assert (
            d.summary()["new_edges"] >= 15
            and conn.execute("SELECT n_edges FROM graph_snapshot WHERE week = ?", (week,)).fetchone()[
                "n_edges"
            ]
            > 0
        )

        # exports
        vrep = export_vault(conn, out_dir=tmp_path / "vault", as_of=NOW.date().isoformat())
        assert vrep.entities >= 20 and vrep.index.exists()
        fed_md = (tmp_path / "vault" / "entities" / "org" / "fed.md").read_text(encoding="utf-8")
        assert "[[kevin-warsh]]" in fed_md and "reports_to" in fed_md and "evidence" in fed_md
        abov_md = (tmp_path / "vault" / "entities" / "org" / "abov.md").read_text(encoding="utf-8")
        assert "이해충돌" in abov_md
        html = render_html(conn, week, out_path=tmp_path / "g.html", as_of=NOW.date().isoformat())
        text = html.read_text(encoding="utf-8")
        assert "cytoscape" in text and "fomc-2026-12-09" in text and "{{" not in text
        png = render_png(conn, week, out_path=tmp_path / "g.png", max_nodes=25, as_of=NOW.date().isoformat())
        assert png is not None and png.exists() and png.stat().st_size > 1000
    finally:
        conn.close()


def test_upsert_edge_weight_follows_story_count() -> None:
    repo.init_db()
    conn = repo.connect()
    try:
        upsert_entity(conn, eid="a", etype="org", name="A")
        upsert_entity(conn, eid="b", etype="org", name="B")
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        for i in range(3):
            upsert_edge(
                conn,
                src="a",
                dst="b",
                rtype="depends_on",
                sign=1,
                weight=0.5,
                confidence=0.6,
                evidence_ids=[f"c{i}"],
                origin="extracted",
                story_id=f"s{i}",
                seen_at=ts,
            )
        row = conn.execute(
            "SELECT * FROM relation WHERE id = ?", (relation_id("a", "b", "depends_on"),)
        ).fetchone()
        assert row["n_stories"] == 3 and row["status"] == "confirmed" and math.isclose(row["weight"], 0.875)
        assert json.loads(row["evidence_ids"]) == ["c0", "c1", "c2"]
    finally:
        conn.close()
