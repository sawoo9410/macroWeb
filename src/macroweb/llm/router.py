"""Model routing: stratum -> tier -> model id, escalation ladder, and price lookups. All values come
from config/models.yaml (PLAN §6.2, §0.3)."""

from __future__ import annotations

from dataclasses import dataclass

from macroweb.config import ModelsConfig, ModelTier, RouteTarget, Stratum, TierName, load_models

LADDER: tuple[TierName, ...] = ("small", "mid", "large")


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelRouter:
    def __init__(self, cfg: ModelsConfig | None = None) -> None:
        self.cfg = cfg or load_models()

    def tier(self, name: TierName) -> ModelTier:
        return self.cfg.tiers[name]

    def model_id(self, name: TierName) -> str:
        return self.tier(name).id

    def alias(self, name: TierName) -> str:
        """Value for `.claude/agents/*.md` `model:` frontmatter (haiku|sonnet|opus)."""
        return self.tier(name).alias

    def tier_for_stratum(self, stratum: Stratum) -> TierName | None:
        target: RouteTarget = self.cfg.routing.strata[stratum]
        return None if target == "none" else target

    def escalate(self, name: TierName) -> TierName | None:
        idx = LADDER.index(name)
        return LADDER[idx + 1] if idx + 1 < len(LADDER) else None

    def effort(self, name: TierName) -> str:
        return self.cfg.defaults.effort[name]

    def estimate_cost(self, name: TierName, usage: Usage, batch: bool = False) -> float:
        t = self.tier(name)
        per_m = 1_000_000
        cost = (
            usage.input_tokens * t.input
            + usage.output_tokens * t.output
            + usage.cache_read_tokens * t.cache_read
            + usage.cache_write_tokens * (t.cache_write_5m or t.input * 1.25)
        ) / per_m
        return cost * self.cfg.batch_discount if batch else cost
