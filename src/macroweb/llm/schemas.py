"""Extraction contract: one Story in -> one JSON out (PLAN §6.1). Strict schemas so the API's structured
output and pydantic validation agree; failures escalate per §6.2.2 rule 1."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RELATION_TYPE = Literal[
    # 구조
    "supplies_to",
    "customer_of",
    "competes_with",
    "owns_stake",
    "subsidiary_of",
    "member_of",
    # 권력
    "appointed_by",
    "reports_to",
    "regulates",
    "votes_on",
    "lobbies",
    "donates_to",
    "allied_with",
    "opposes",
    "pressures",
    # 인과·이익
    "benefits_from",
    "hurt_by",
    "depends_on",
    "exposed_to",
    "triggers",
    "hedges",
    # 통계
    "correlates_with",
    "leads",
    # 담론
    "argues",
    "predicts",
    "denies",
    "confirms",
    # 시간
    "succeeds",
    "precedes",
    "scheduled_for",
]
RELATION_TYPES: frozenset[str] = frozenset(get_args(RELATION_TYPE))
RELATION_ALIASES: dict[str, str] = {
    "hurts": "hurt_by",
    "benefits": "benefits_from",
    "supplies": "supplies_to",
}

ENTITY_TYPES = Literal[
    "person",
    "org",
    "country_bloc",
    "policy",
    "asset",
    "product_tech",
    "event",
    "theme",
    "indicator",
    "scenario",
]
CLAIM_TYPES = Literal["numeric", "event", "quote", "forecast", "attribution"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimOut(Strict):
    text: str = Field(description="원자적 한 문장 = 한 사실")
    type: CLAIM_TYPES
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    value: float | None = None
    unit: str | None = Field(
        default=None, description="%, bp, USD, KRW, 조원, QoQ, YoY 등. 숫자는 value/unit 분리"
    )
    time_ref: str | None = Field(default=None, description="ISO date 또는 기간 표현")
    cited_primary_doc: str | None = Field(default=None, description="기사가 인용한 1차 문서 제목+날짜")
    anonymous_source: bool = False


class EntityOut(Strict):
    name: str
    type: ENTITY_TYPES
    role_hint: str | None = None


class RelationOut(Strict):
    src: str
    dst: str
    type: RELATION_TYPE
    sign: Literal[-1, 0, 1] = 0
    quote_span: str | None = Field(default=None, description="기사가 명시한 근거 문장. 추론 금지")

    @field_validator("type", mode="before")
    @classmethod
    def _normalise_type(cls, v: object) -> object:
        return RELATION_ALIASES.get(v, v) if isinstance(v, str) else v


class CuiBonoOut(Strict):
    entity: str
    effect: Literal["benefits", "hurt"]
    why: str


class SentimentOut(Strict):
    market: float = Field(ge=-1, le=1)
    policy_hawkish: float = Field(ge=-1, le=1)


class ExtractionResult(Strict):
    summary_ko: str = Field(description="3문장 이내 한국어 요약")

    @model_validator(mode="before")
    @classmethod
    def _drop_unknown_relations(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("relations"), list):
            kept = []
            dropped = 0
            for r in data["relations"]:
                t = r.get("type") if isinstance(r, dict) else None
                if isinstance(t, str):
                    t = RELATION_ALIASES.get(t, t)
                if t in RELATION_TYPES:
                    kept.append(r)
                else:
                    dropped += 1
            if dropped:
                data = {
                    **data,
                    "relations": kept,
                    "red_flags": [*list(data.get("red_flags") or []), f"dropped_unknown_relations:{dropped}"],
                }
        return data

    claims: list[ClaimOut]
    entities: list[EntityOut]
    relations: list[RelationOut]
    cui_bono: list[CuiBonoOut]
    sentiment: SentimentOut
    novelty_hint: Literal["new", "update", "recycled"]
    red_flags: list[str]


class LanguageSignals(Strict):
    """검증 루브릭(언어 신호) 출력 — PLAN 부록 D."""

    sensational_headline: float = Field(ge=0, le=1)
    hedging_density: float = Field(ge=0, le=1)
    anonymous_ratio: float = Field(ge=0, le=1)
    has_named_author: bool
    numbers_without_source: int = Field(ge=0)
    urgency_cues: float = Field(ge=0, le=1)
    satire_probability: float = Field(ge=0, le=1)
    ad_or_pump_probability: float = Field(ge=0, le=1)
    language_risk: float = Field(ge=0, le=1)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for structured outputs: every object closed (additionalProperties=false) and every
    property required, which is what the API's `json_schema` format expects for batch requests."""

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                tighten(v)
        elif isinstance(node, list):
            for v in node:
                tighten(v)

    schema = model.model_json_schema()
    tighten(schema)
    return schema
