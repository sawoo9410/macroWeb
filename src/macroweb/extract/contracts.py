"""L3 extraction contract (PLAN §6): what a Story hands to the model, how a batch request is identified so
re-runs are idempotent, and the two seams Phase 2 implements (story selection, extractor). No LLM calls here."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from macroweb.config import Stratum, TierName

CUSTOM_ID_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9_-]{1,8})_(?P<story>[a-z0-9-]+)_v(?P<version>\d+)_(?P<tier>small|mid|large)$"
)
CUSTOM_ID_MAX = 64  # Message Batches API limit


@dataclass
class StoryInput:
    """One Story as the extractor sees it (representative article + source metadata)."""

    story_id: str
    source_id: str
    tier: int
    stratum: Stratum
    title: str
    text: str
    url: str
    published_at: str | None
    lang: str
    n_independent: int = 1
    impact_hint: float | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionRequest:
    story_id: str
    prompt_version: int
    model_tier: TierName
    stratum: Stratum
    escalation_reason: str | None = None

    def custom_id(self, prefix: str = "ext") -> str:
        return make_custom_id(prefix, self.story_id, self.prompt_version, self.model_tier)


@dataclass
class ExtractionOutcome:
    request: ExtractionRequest
    status: str  # succeeded | failed | quarantined | escalated
    result_json: str | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str | None = None


def make_custom_id(prefix: str, story_id: str, prompt_version: int, tier: TierName) -> str:
    """`ext_<story_id>_v<N>_<tier>` — only [A-Za-z0-9_-], ≤ 64 chars (API limit); story ids are `st-<16 hex>`."""
    cid = f"{prefix}_{story_id}_v{prompt_version}_{tier}"
    if not CUSTOM_ID_RE.match(cid) or len(cid) > CUSTOM_ID_MAX:
        raise ValueError(f"invalid custom_id {cid!r}")
    return cid


def parse_custom_id(cid: str) -> tuple[str, int, TierName]:
    m = CUSTOM_ID_RE.match(cid)
    if not m:
        raise ValueError(f"not a macroweb custom_id: {cid!r}")
    tier: TierName = m.group("tier")  # type: ignore[assignment]
    return m.group("story"), int(m.group("version")), tier


class StorySelector(Protocol):
    """Phase 2: picks ≤ daily_story_cap T1/T2 stories (theme similarity × tier) plus every T0 document."""

    def select(self, conn: sqlite3.Connection, day: str) -> list[StoryInput]: ...


class Extractor(Protocol):
    """Phase 2: wraps `macroweb.llm.client.LLMClient` with the batch ledger (`llm_batch` / `extraction`)."""

    def submit_batch(self, requests: Iterable[tuple[ExtractionRequest, StoryInput]]) -> str: ...

    def collect_batch(self, batch_id: str) -> list[ExtractionOutcome]: ...

    def extract_now(self, request: ExtractionRequest, story: StoryInput) -> ExtractionOutcome: ...
