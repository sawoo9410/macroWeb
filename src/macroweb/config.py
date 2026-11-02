"""Typed loaders for config/*.yaml and prompt files. Every file has a schema; `validate_all()` backs
`macroweb config validate`, the PostToolUse lint hook and the pre-commit hook."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from macroweb.paths import CONFIG_DIR, PROMPTS_DIR

TIER_PRIOR: dict[int, float] = {0: 0.95, 1: 0.80, 2: 0.65, 3: 0.70, 4: 0.30, 5: 0.15}
Stratum = Literal["S-DATA", "S-T0-STMT", "S-T0-LONG", "S-T1", "S-T1-KO", "S-T2", "S-T4", "S-ER"]
TierName = Literal["small", "mid", "large"]
RouteTarget = Literal["none", "small", "mid", "large"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- sources.yaml (PLAN §4.2, 부록 B) -------------------------------------------------------------
class Source(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    tier: int = Field(ge=0, le=5)
    kind: Literal["rss", "html", "api", "playwright", "pdf", "json"]
    url: str
    lang: str = "en"
    country: str | None = None
    topics: list[str] = Field(default_factory=list)
    parent_org: str | None = None
    parser: str = "rss_default"
    rate_limit_s: float = Field(default=2.0, ge=2.0)
    paywall: bool = False
    enabled: bool = True
    credibility_prior: float | None = Field(default=None, ge=0.0, le=1.0)
    stratum: Stratum | None = None
    auth_env: str | None = None
    probe_url: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    fetch_body: bool = False  # 본문(trafilatura) 수집 여부 — paywall 소스는 무시
    interval_s: int | None = Field(
        default=None, ge=900, le=86400
    )  # 고정 주기(초). 없으면 피드 창 기반 적응 주기
    notes: str | None = None

    @model_validator(mode="after")
    def _default_prior(self) -> Source:
        if self.credibility_prior is None:
            self.credibility_prior = TIER_PRIOR[self.tier]
        return self


class SourcesFile(Strict):
    sources: list[Source]

    @model_validator(mode="after")
    def _unique_ids(self) -> SourcesFile:
        ids = [s.id for s in self.sources]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate source ids: {dupes}")
        return self


# --- models.yaml (PLAN §6.2, §16.4, §0.3) ------------------------------------------------------------
class ModelTier(Strict):
    id: str
    alias: Literal["haiku", "sonnet", "opus", "fable"]
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float = Field(ge=0)
    cache_write_5m: float | None = Field(default=None, ge=0)
    note: str | None = None


class Escalation(Strict):
    enabled: bool = True
    daily_cap: int = Field(default=8, ge=0)
    reasons: list[str]


class Audit(Strict):
    reference_tier: TierName
    weekly_sample_per_stratum: int
    long_doc_monthly_sample: int
    error_rate_alert: float


class Routing(Strict):
    strata: dict[Stratum, RouteTarget]
    large_monthly_quota_long_docs: int = 6
    escalation: Escalation
    audit: Audit


class DegradeStep(Strict):
    at_pct: float
    action: str


class Budget(Strict):
    monthly_cap_usd: float
    soft_limit_pct: float
    degrade: list[DegradeStep]
    weekly_editorial_cap_usd: float


class WeeklyRunner(Strict):
    mode: Literal["claude_headless", "api"]
    api_fallback: bool = False
    max_turns: int = 60
    max_budget_usd: float = 8.0


class Defaults(Strict):
    effort: dict[TierName, Literal["low", "medium", "high", "xhigh", "max"]]
    max_tokens: dict[str, int]


class ModelsConfig(Strict):
    updated: str
    price_source: str
    tiers: dict[TierName, ModelTier]
    batch_discount: float = Field(ge=0, le=1)
    defaults: Defaults
    routing: Routing
    budget: Budget
    weekly_runner: WeeklyRunner

    @model_validator(mode="after")
    def _all_tiers(self) -> ModelsConfig:
        missing = {"small", "mid", "large"} - set(self.tiers)
        if missing:
            raise ValueError(f"models.yaml tiers missing: {sorted(missing)}")
        return self


# --- quality.yaml (PLAN §10.5) --------------------------------------------------------------------
class QualityCheck(Strict):
    name: str
    what: str
    auto: str | None = None
    human_or_llm: str | None = None
    alert: dict[str, Any] = Field(default_factory=dict)
    phase: int


class QualityConfig(Strict):
    checks: dict[Literal["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"], QualityCheck]
    gate: dict[str, str]
    recalibrate_after_weeks: int = 8


# --- small registries -----------------------------------------------------------------------------
class Trap(Strict):
    id: str
    description: str
    signals: list[str]
    label_hint: str | None = None


class TrapsConfig(Strict):
    traps: list[Trap]


class Theme(Strict):
    id: str
    name: str
    keywords: list[str]
    seed_entities: list[str] = Field(default_factory=list)


class ThemesConfig(Strict):
    themes: list[Theme]


class CalendarEvent(Strict):
    id: str
    name: str
    date: str
    time_kst: str | None = None
    kind: Literal["fomc", "data", "election", "earnings", "bok", "auction", "other"]
    status: Literal["confirmed", "unverified"]
    source: str
    watch: str | None = None


class CalendarConfig(Strict):
    events: list[CalendarEvent]


class KeyPerson(Strict):
    id: str
    name: str | None = None
    role: str
    org: str
    why: str
    verify: bool = True
    conflict_of_interest: bool = False


class KeyPersonsConfig(Strict):
    persons: list[KeyPerson]


class AliasesConfig(Strict):
    aliases: dict[str, list[str]]


class Tolerance(Strict):
    abs: float | None = None
    rel: float | None = None
    note: str | None = None


class TolerancesConfig(Strict):
    default_rel: float
    by_unit: dict[str, Tolerance]
    by_pair: dict[str, Tolerance] = Field(
        default_factory=dict
    )  # "KEY_A~KEY_B": 같은 지표의 두 출처 허용 오차


class GlossaryConfig(Strict):
    terms: dict[str, str]


class CostJob(Strict):
    name: str
    tier: TierName
    batch: bool = False
    per: Literal["day", "week", "month"]
    count: float
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    overhead: float = 1.0
    group: str | None = None


class CostWorkload(Strict):
    days_per_month: float = 30
    weeks_per_month: float = 4.33
    jobs: list[CostJob]


# --- loaders --------------------------------------------------------------------------------------
def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_sources(path: Path | None = None) -> SourcesFile:
    raw = load_yaml(path or CONFIG_DIR / "sources.yaml")
    if isinstance(raw, list):
        raw = {"sources": raw}
    return SourcesFile.model_validate(raw)


def load_models(path: Path | None = None) -> ModelsConfig:
    return ModelsConfig.model_validate(load_yaml(path or CONFIG_DIR / "models.yaml"))


def load_quality(path: Path | None = None) -> QualityConfig:
    return QualityConfig.model_validate(load_yaml(path or CONFIG_DIR / "quality.yaml"))


def load_cost_workload(path: Path | None = None) -> CostWorkload:
    return CostWorkload.model_validate(load_yaml(path or CONFIG_DIR / "cost_workload.yaml"))


SCHEMAS: dict[str, type[BaseModel]] = {
    "sources.yaml": SourcesFile,
    "models.yaml": ModelsConfig,
    "quality.yaml": QualityConfig,
    "traps.yaml": TrapsConfig,
    "themes.yaml": ThemesConfig,
    "calendar.yaml": CalendarConfig,
    "key_persons.yaml": KeyPersonsConfig,
    "aliases.yaml": AliasesConfig,
    "tolerances.yaml": TolerancesConfig,
    "glossary.yaml": GlossaryConfig,
    "cost_workload.yaml": CostWorkload,
}


@dataclass
class ValidationResult:
    name: str
    path: Path
    ok: bool
    message: str


def validate_config_file(path: Path) -> ValidationResult:
    schema = SCHEMAS.get(path.name)
    if schema is None:
        return ValidationResult(path.name, path, True, "no schema registered (skipped)")
    try:
        raw = load_yaml(path)
        if path.name == "sources.yaml" and isinstance(raw, list):
            raw = {"sources": raw}
        schema.model_validate(raw)
        return ValidationResult(path.name, path, True, "ok")
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        return ValidationResult(path.name, path, False, str(exc).strip().splitlines()[0][:300])


def validate_prompt_file(path: Path) -> ValidationResult:
    """Prompts are versioned files: `prompts/<name>/v<N>.md` with a `version:` frontmatter line and a
    CHANGELOG entry (PLAN §6.3)."""
    if path.name == "CHANGELOG.md" or path.suffix != ".md":
        return ValidationResult(str(path.relative_to(PROMPTS_DIR)), path, True, "skipped")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ValidationResult(path.name, path, False, "missing frontmatter (--- version: N ---)")
    header = text.split("---", 2)[1]
    if "version:" not in header:
        return ValidationResult(path.name, path, False, "frontmatter lacks `version:`")
    version = header.split("version:", 1)[1].strip().splitlines()[0].strip()
    changelog = path.parent / "CHANGELOG.md"
    if not changelog.exists() or f"v{version}" not in changelog.read_text(encoding="utf-8"):
        return ValidationResult(path.name, path, False, f"CHANGELOG.md lacks an entry for v{version}")
    return ValidationResult(str(path.relative_to(PROMPTS_DIR)), path, True, f"ok (v{version})")


def validate_all(only: Path | None = None) -> list[ValidationResult]:
    if only is not None:
        only = only.resolve()
        if only.is_relative_to(PROMPTS_DIR.resolve()):
            return [validate_prompt_file(only)]
        return [validate_config_file(only)]
    results = [validate_config_file(CONFIG_DIR / name) for name in SCHEMAS if (CONFIG_DIR / name).exists()]
    results += [
        ValidationResult(n, CONFIG_DIR / n, False, "missing file")
        for n in SCHEMAS
        if not (CONFIG_DIR / n).exists()
    ]
    for p in sorted(PROMPTS_DIR.rglob("*.md")):
        if p.name != "CHANGELOG.md" and p.name != "README.md":
            results.append(validate_prompt_file(p))
    return results
