from pathlib import Path

from macroweb.db import repo


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "db" / "t.sqlite"
    first = repo.init_db(p)
    assert first["created"] is True
    assert first["schema_version"] >= repo.SCHEMA_VERSION
    assert first["applied_migrations"] == ["0002_collect.sql"]
    for t in (
        "source",
        "article",
        "story",
        "claim",
        "evidence",
        "entity",
        "relation",
        "thesis",
        "run",
        "market",
        "quality_run",
        "report_citation",
    ):
        assert t in first["tables"], t
    second = repo.init_db(p)
    assert second["created"] is False
    assert second["applied_migrations"] == []


def test_integrity_fts_and_run_ledger(tmp_path: Path) -> None:
    p = tmp_path / "t.sqlite"
    repo.init_db(p)
    conn = repo.connect(p)
    try:
        assert repo.integrity_check(conn) == "ok"
        assert repo.fts5_available(conn)
        conn.execute("INSERT INTO source(id, name, tier) VALUES ('s1', 'S', 1)")
        conn.execute(
            "INSERT INTO article(id, url, canonical_url, source_id, title, text) VALUES ('a1', 'u', 'u', 's1', '연준 금리 동결', '본문 금리')"
        )
        conn.commit()
        # trigram tokenizer: each query term needs >= 3 characters; wrap Korean phrases in quotes (Phase 2 note)
        hits = conn.execute(
            "SELECT rowid FROM article_fts WHERE article_fts MATCH '\"금리 동결\"'"
        ).fetchall()
        assert len(hits) == 1
        run_id = repo.start_run(conn, "collect", {"extract": "v1"})
        repo.finish_run(
            conn, run_id, "ok", {"n": 1}, tokens_in=100, tokens_out=10, model_tier="small", cost_usd=0.01
        )
        assert repo.month_cost_usd(conn) == 0.01
        assert repo.recent_runs(conn)[0]["status"] == "ok"
    finally:
        conn.close()
