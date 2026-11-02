"""Monthly cost estimate = config/cost_workload.yaml volumes × config/models.yaml prices (PLAN §16.4).
Jobs in the `weekly_editorial` group are billed to the subscription when weekly_runner.mode is
claude_headless (ADR-0002), so they are reported separately and excluded from the API total."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from macroweb.config import CostJob, CostWorkload, ModelsConfig, load_cost_workload, load_models
from macroweb.llm.router import ModelRouter, Usage


@dataclass
class CostLine:
    name: str
    tier: str
    batch: bool
    group: str | None
    monthly_usd: float


@dataclass
class CostEstimate:
    lines: list[CostLine]
    api_total_usd: float
    subscription_equivalent_usd: float
    cap_usd: float
    cap_pct: float | None
    weekly_runner_mode: str
    track_a_runner_mode: str
    subscription_calls_per_day: float
    subscription_tokens_per_day: float
    price_source: str
    prices_updated: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _periods(job: CostJob, wl: CostWorkload) -> float:
    return {"day": wl.days_per_month, "week": wl.weeks_per_month, "month": 1.0}[job.per]


def estimate(models: ModelsConfig | None = None, workload: CostWorkload | None = None) -> CostEstimate:
    models = models or load_models()
    workload = workload or load_cost_workload()
    router = ModelRouter(models)
    lines: list[CostLine] = []
    for job in workload.jobs:
        usage = Usage(
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            cache_read_tokens=job.cached_input_tokens,
        )
        per_call = router.estimate_cost(job.tier, usage, batch=job.batch)
        monthly = per_call * job.count * _periods(job, workload) * job.overhead
        lines.append(CostLine(job.name, job.tier, job.batch, job.group, monthly))
    subscription_groups: set[str | None] = set()
    if models.weekly_runner.mode == "claude_headless":
        subscription_groups.add("weekly_editorial")
    if models.track_a_runner.mode == "claude_headless":
        subscription_groups.add("track_a")
    api_total = sum(line.monthly_usd for line in lines if line.group not in subscription_groups)
    sub_total = sum(line.monthly_usd for line in lines if line.group in subscription_groups)
    # subscription volume: calls/day and tokens/day incl. the per-call harness overhead (ADR-0007 measurement)
    calls_day = 0.0
    tokens_day = 0.0
    for job in workload.jobs:
        if job.group not in subscription_groups:
            continue
        per_day = job.count * _periods(job, workload) / workload.days_per_month
        calls_day += per_day
        tokens_day += per_day * (
            job.input_tokens
            + job.cached_input_tokens
            + job.output_tokens
            + workload.headless_overhead_tokens_per_call
        )
    cap = models.budget.monthly_cap_usd
    return CostEstimate(
        lines=lines,
        api_total_usd=api_total,
        subscription_equivalent_usd=sub_total,
        cap_usd=cap,
        cap_pct=(api_total / cap * 100) if cap else None,
        weekly_runner_mode=models.weekly_runner.mode,
        track_a_runner_mode=models.track_a_runner.mode,
        subscription_calls_per_day=calls_day,
        subscription_tokens_per_day=tokens_day,
        price_source=models.price_source,
        prices_updated=models.updated,
    )
