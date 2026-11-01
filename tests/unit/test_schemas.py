import pytest
from pydantic import ValidationError

from macroweb.llm.schemas import ExtractionResult, RelationOut, strict_json_schema

SAMPLE = {
    "summary_ko": "연준이 금리를 동결했다. 두 위원이 인상을 주장했다.",
    "claims": [
        {
            "text": "FOMC held rates at 3.75–4.00%",
            "type": "event",
            "subject": "FOMC",
            "predicate": "held",
            "object": "rates",
            "value": None,
            "unit": None,
            "time_ref": "2026-10-28",
            "cited_primary_doc": "FOMC statement 2026-10-28",
            "anonymous_source": False,
        }
    ],
    "entities": [{"name": "Kevin Warsh", "type": "person", "role_hint": "Fed Chair"}],
    "relations": [
        {"src": "Trump", "dst": "Fed", "type": "pressures", "sign": -1, "quote_span": "..."},
        {"src": "rate hike", "dst": "growth stocks", "type": "hurts", "sign": -1, "quote_span": None},
    ],
    "cui_bono": [{"entity": "dollar", "effect": "benefits", "why": "higher for longer"}],
    "sentiment": {"market": -0.4, "policy_hawkish": 0.7},
    "novelty_hint": "update",
    "red_flags": ["sensational_headline"],
}


def test_extraction_result_validates_and_normalizes_aliases() -> None:
    res = ExtractionResult.model_validate(SAMPLE)
    assert res.relations[1].type == "hurt_by"
    assert res.claims[0].time_ref == "2026-10-28"


def test_unknown_relation_type_rejected() -> None:
    with pytest.raises(ValidationError):
        RelationOut(src="a", dst="b", type="likes", sign=0)


def test_strict_schema_closes_objects() -> None:
    schema = strict_json_schema(ExtractionResult)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    claim_schema = schema["$defs"]["ClaimOut"]
    assert claim_schema["additionalProperties"] is False
    assert "anonymous_source" in claim_schema["required"]
