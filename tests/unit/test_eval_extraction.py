"""Extraction eval set: bucketed story selection, label templates, and scoring against stored claims."""

from __future__ import annotations

from pathlib import Path

import yaml
from test_verify_v1 import NOW, T0_RESULT, T1_RESULT, _collect_fixtures, _story_for

from macroweb.db import repo
from macroweb.eval.extraction import (
    build,
    jaccard,
    load_labels,
    norm_tokens,
    pick_stories,
    score,
    score_story,
    status,
)
from macroweb.extract.persist import persist_result
from macroweb.llm.schemas import ExtractionResult


def test_norm_tokens_handles_hangul_and_numbers() -> None:
    a = norm_tokens("코스피가 2,600.5에 마감했다")
    b = norm_tokens("코스피 2,600.5 마감")
    assert "코스" in a and "2,600.5" in a and jaccard(a, b) >= 0.5
    assert jaccard(norm_tokens("Inflation rose to 3.8 per cent"), norm_tokens("Energy prices fell")) < 0.2


def test_score_story_matches_text_and_numbers() -> None:
    label = {
        "story_id": "x",
        "stratum": "S-T1-KO",
        "lang": "ko",
        "claims": [
            {"text": "코스피가 2,600.5에 마감했다", "type": "numeric", "value": 2600.5, "unit": "pt"},
            {"text": "외국인은 3거래일 연속 순매도했다", "type": "event"},
            {"text": "한국은행이 기준금리를 동결했다", "type": "event"},  # not predicted → fn
        ],
    }
    preds = [
        {"text": "코스피가 2,600.5에 마감했다", "value": 2600.5},
        {"text": "관계자에 따르면 외국인은 3거래일 연속 순매도했다", "value": None},
        {"text": "코스피가 1.2% 하락했다", "value": 1.2},  # unmatched → fp
    ]
    sc = score_story(label, preds)
    assert sc.tp == 2 and sc.n_labels == 3 and sc.n_preds == 3
    assert round(sc.precision, 3) == 0.667 and round(sc.recall, 3) == 0.667
    assert sc.numeric_labels == 1 and sc.numeric_wrong == 0
    # same text but the model misread the number → counted as a numeric error, still a text match
    wrong = score_story(label, [{"text": "코스피가 2,600.5에 마감했다", "value": 2650.0}])
    assert wrong.tp == 1 and wrong.numeric_wrong == 1


def test_build_and_score_round_trip(tmp_path: Path) -> None:
    _collect_fixtures()
    conn = repo.connect()
    try:
        t0 = _story_for(conn, "fed_press", tier=0, stratum="S-T0-STMT", impact=0.9)
        t1 = _story_for(conn, "yna_economy", tier=1, stratum="S-T1-KO", impact=0.95)
        # three independent outlets force a story past the theme gate (extract.yaml min_independent_to_force)
        conn.execute("UPDATE story SET n_independent = 3 WHERE id = ?", (t1.story_id,))
        conn.commit()
        persist_result(
            conn, t0, ExtractionResult.model_validate(T0_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        persist_result(
            conn, t1, ExtractionResult.model_validate(T1_RESULT), extracted_by="test@extract@v2", now=NOW
        )
        quota = {("S-T1-KO", "ko"): 2, ("S-T0-STMT", "en"): 1}
        picked = pick_stories(conn, quota=quota, min_chars=20)
        assert {(p["stratum"], p["lang"]) for p in picked} <= set(quota)
        assert picked and any(p["extracted"] for p in picked)  # already-extracted stories are preferred
        eval_dir = tmp_path / "eval"
        stories = build(conn, eval_dir=eval_dir, quota=quota, min_chars=20)
        assert (eval_dir / "stories.jsonl").exists()
        templates = sorted((eval_dir / "labels").glob("*.yaml"))
        assert len(templates) == len(stories) and load_labels(eval_dir) == []  # unlabeled → nothing to score
        assert status(eval_dir)["labeled"] == 0
        # the labeler fills the yna story: two true claims and one the article does not support
        path = eval_dir / "labels" / f"{t1.story_id}.yaml"
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert d["story_id"] == t1.story_id and d["labeler"] is None
        d["labeler"] = "sangwoo"
        d["claims"] = [
            {"text": "코스피가 2,600.5에 마감했다", "type": "numeric", "value": 2600.5, "unit": "pt"},
            {"text": "관계자는 연내 금리 인하 가능성이 있다고 말했다", "type": "attribution"},
            {"text": "정부가 추경을 편성했다", "type": "event"},
        ]
        path.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        rep = score(conn, eval_dir=eval_dir)
        assert len(rep.stories) == 1 and rep.stories[0].tp == 2 and rep.stories[0].n_preds == 5
        by = rep.by_stratum()["S-T1-KO"]
        assert by["stories"] == 1 and by["recall"] == round(2 / 3, 3) and by["numeric_error_rate"] == 0.0
        assert list((eval_dir / "results").glob("*-db.json"))
        # build again keeps the set and never touches the filled label
        build(conn, eval_dir=eval_dir, quota=quota, min_chars=20)
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["labeler"] == "sangwoo"
        # routing experiment path: no ledger result for tier 'large' → skipped, not scored
        rep_large = score(conn, eval_dir=eval_dir, tier="large", write=False)
        assert rep_large.stories == [] and rep_large.skipped == [t1.story_id]
    finally:
        conn.close()
