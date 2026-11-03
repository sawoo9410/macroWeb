"""verify v1 (ADR-0009): deterministic signals over fixture-collected stories. Claims are persisted directly
through `persist_result` (no model); the market point and the aged duplicate article are test doubles."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from macroweb.collect.fixtures import list_fixtures, read_fixture
from macroweb.collect.http import make_client
from macroweb.collect.pipeline import run_collect
from macroweb.config import load_sources, load_verify
from macroweb.db import repo
from macroweb.extract.contracts import StoryInput
from macroweb.extract.persist import persist_result
from macroweb.llm.schemas import ExtractionResult
from macroweb.verify.run import run_verify
from macroweb.verify.signals import recycled_check, unit_family

NOW = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)
SOURCES = ["fed_press", "yna_economy"]
EMPTY = {"entities": [], "relations": [], "cui_bono": [], "sentiment": {"market": 0.0, "policy_hawkish": 0.0}}


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


T0_RESULT = {
    "summary_ko": "테스트 요약.",
    "claims": [
        _claim(
            "The Committee decided to maintain the target range for the federal funds rate.",
            "event",
            subject="FOMC",
            predicate="maintain",
            object="target range",
        )
    ],
    "novelty_hint": "new",
    "red_flags": [],
    **EMPTY,
}
T1_RESULT = {
    "summary_ko": "테스트 요약.",
    "claims": [
        _claim(
            "코스피가 2,600.5에 마감했다",
            "numeric",
            subject="코스피",
            predicate="마감",
            value=2600.5,
            unit="pt",
        ),
        _claim(
            "코스피가 2,700.0에 마감했다",
            "numeric",
            subject="코스피",
            predicate="마감",
            value=2700.0,
            unit="pt",
        ),
        _claim("코스피가 1.2% 하락했다", "numeric", subject="코스피", predicate="하락", value=1.2, unit="%"),
        _claim(
            "관계자에 따르면 외국인은 3거래일 연속 순매도했다",
            "event",
            subject="외국인",
            anonymous_source=True,
        ),
        _claim(
            "관계자는 연내 금리 인하 가능성이 있다고 말했다",
            "attribution",
            subject="관계자",
            anonymous_source=True,
        ),
    ],
    "novelty_hint": "new",
    "red_flags": ["제목 과장", "저자 없음", "전망치를 확정치처럼 서술", "'외신 종합' 원문 링크 없음"],
    **EMPTY,
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


def _story_for(conn, source_id: str, *, tier: int, stratum: str, impact: float) -> StoryInput:  # type: ignore[no-untyped-def]
    row = conn.execute(
        """SELECT s.id AS story_id, a.id AS aid, a.title, a.text, a.url, a.published_at, a.lang
           FROM story s JOIN story_article sa ON sa.story_id = s.id JOIN article a ON a.id = sa.article_id
           WHERE a.source_id = ? AND a.published_at IS NOT NULL ORDER BY a.published_at DESC LIMIT 1""",
        (source_id,),
    ).fetchone()
    assert row, f"no article from {source_id} in the fixtures"
    conn.execute(
        "UPDATE story SET rep_article_id = ?, impact = ?, stratum = ? WHERE id = ?",
        (row["aid"], impact, stratum, row["story_id"]),
    )
    conn.commit()
    return StoryInput(
        story_id=row["story_id"],
        source_id=source_id,
        tier=tier,
        stratum=stratum,  # type: ignore[arg-type]
        title=row["title"] or "",
        text=row["text"] or "",
        url=row["url"],
        published_at=row["published_at"],
        lang=row["lang"] or "ko",
        impact_hint=impact,
        extra={"rep_article_id": row["aid"]},
    )


def _labels(conn, story_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        r["text"]: r["label"]
        for r in conn.execute("SELECT text, label FROM claim WHERE story_id = ?", (story_id,)).fetchall()
    }


def test_unit_family_distinguishes_levels_from_changes() -> None:
    assert unit_family("pt") == "index" and unit_family("원") == "KRW" and unit_family("%") == "%"
    assert unit_family("% YoY") == "change" and unit_family("bp") == "bp" and unit_family(None) is None


def test_verify_v1_labels_review_queue_and_recycled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        # a KOSPI close on the trading day before the yna article (test double for the NAVER:KOSPI series)
        pub_day = (t1.published_at or "")[:10]
        conn.execute(
            "INSERT INTO market(date, key, value, source) VALUES (?, 'NAVER:KOSPI', 2600.9, 'test')",
            (pub_day,),
        )
        conn.commit()

        rep = run_verify(conn, now=NOW, day="2026-11-02")
        assert rep.considered == 6 and rep.updated == 6, rep.render()
        assert _labels(conn, t0.story_id) == {
            T0_RESULT["claims"][0]["text"]: "VERIFIED"
        }  # primary document itself
        l1 = _labels(conn, t1.story_id)
        assert l1["코스피가 2,600.5에 마감했다"] == "VERIFIED"  # within tolerances by_unit index (0.2 %)
        assert l1["코스피가 2,700.0에 마감했다"] == "DISPUTED"  # level claim 99 points off
        assert l1["코스피가 1.2% 하락했다"] == "SINGLE_SOURCE"  # a change, never compared with a level
        assert l1["관계자에 따르면 외국인은 3거래일 연속 순매도했다"] == "SINGLE_SOURCE"
        assert l1["관계자는 연내 금리 인하 가능성이 있다고 말했다"] == "UNVERIFIABLE"
        row = conn.execute(
            "SELECT confidence, signals_json FROM claim WHERE text = ?", ("코스피가 2,600.5에 마감했다",)
        ).fetchone()
        v = json.loads(row["signals_json"])["verify"]
        assert v["numeric"]["key"] == "NAVER:KOSPI" and v["numeric"]["match"] == 1.0 and v["prior"] == 0.8
        # yna articles carry a byline, so the risk comes from the red_flags (title, forecast-as-fact, no source link)
        assert v["language_risk"] >= 0.5 and "sensational_title" in v["language_feats"]
        assert "no_author" not in v["language_feats"] and row["confidence"] > 0.5
        # review queue: the DISPUTED level claim and the anonymous event claim are high impact (0.95) and low
        # confidence → two open items + md; the attribution claim (impact 0.95 × 0.7) stays below the gate
        open_rows = conn.execute(
            "SELECT claim_id, reason FROM review_queue WHERE decided_at IS NULL"
        ).fetchall()
        assert len(open_rows) == 2 and rep.review_added == 2
        assert rep.review_md and rep.review_md.exists()
        md = rep.review_md.read_text()
        assert all(r["claim_id"] in md for r in open_rows) and "수치 불일치 NAVER:KOSPI" in md
        # idempotent: same labels, no duplicate queue rows
        rep2 = run_verify(conn, now=NOW, day="2026-11-02")
        assert rep2.review_added == 0 and _labels(conn, t1.story_id) == l1
        assert conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0] == 2

        # signal 5: an identical title published 120 days earlier makes the story RECYCLED
        a = conn.execute("SELECT * FROM article WHERE id = ?", (t1.extra["rep_article_id"],)).fetchone()
        assert recycled_check(conn, a, min_age_days=90, max_hamming=3)[0] == 0.0
        old_pub = (datetime.fromisoformat(a["published_at"]) - timedelta(days=120)).isoformat()
        conn.execute(
            """INSERT INTO article(id, url, canonical_url, source_id, title, published_at, fetched_at, lang, text, title_simhash, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')""",
            (
                "old0000000000001",
                a["url"] + "?old=1",
                a["canonical_url"] + "?old=1",
                a["source_id"],
                a["title"],
                old_pub,
                old_pub,
                a["lang"],
                a["text"],
                a["title_simhash"],
            ),
        )
        conn.commit()
        assert recycled_check(conn, a, min_age_days=90, max_hamming=3)[0] == 1.0
        rep3 = run_verify(conn, now=NOW, relabel=True, day="2026-11-02", write_md=False)
        assert rep3.considered == 6
        assert set(_labels(conn, t1.story_id).values()) == {"RECYCLED"}
        assert _labels(conn, t0.story_id) == {T0_RESULT["claims"][0]["text"]: "VERIFIED"}
        assert load_verify().labels.report_use["RECYCLED"] == "notes_only"
    finally:
        conn.close()
