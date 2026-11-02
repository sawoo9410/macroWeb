"""L4 verification contract (PLAN §7.1–7.3): the 8 labels, the 12 signals, the confidence formula and the
label decision rules. Pure functions over a `SignalVector`; weights/rules come from config/verify.yaml.
Signal *computation* (fetching primary docs, data-API comparison, …) arrives in Phase 2/6 — this module only
fixes the interface those computations must fill in."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, StrEnum

from macroweb.config import VerifyConfig, load_verify


class Label(StrEnum):
    VERIFIED = "VERIFIED"
    CORROBORATED = "CORROBORATED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    DISPUTED = "DISPUTED"
    DEBUNKED = "DEBUNKED"
    UNVERIFIABLE = "UNVERIFIABLE"
    RECYCLED = "RECYCLED"
    SPAM_SATIRE = "SPAM_SATIRE"


class Signal(int, Enum):
    """PLAN §7.2 numbering. The value is the signal number used in `verify.yaml signals_phase`."""

    SOURCE_PRIOR = 1
    INDEPENDENT_CROSS_CHECK = 2
    PRIMARY_DOC_TRACE = 3
    NUMERIC_CHECK = 4
    TIME_CONSISTENCY = 5
    LANGUAGE = 6
    DOMAIN_RISK = 7
    RUMOR_LIFECYCLE = 8
    CORRECTION_WATCH = 9
    MARKET_REACTION = 10
    GENERATED_CONTENT = 11
    RED_TEAM_DEBATE = 12


@dataclass
class SignalVector:
    """Inputs to the score. Floats are 0–1 unless noted; `None` means "signal not computed" (treated as 0 and
    recorded in `missing`)."""

    prior: float = 0.5  # source_stats.credibility
    n_independent: int = 1  # independent outlets (syndication excluded)
    primary_match: float | None = None  # 1 = matches the cited primary document, -1 = contradicts
    numeric_match: float | None = None  # 1 = within tolerance of data API, -1 = outside
    recycled: float | None = None  # 1 = re-run of an old story
    language_risk: float | None = None  # LanguageSignals.language_risk
    domain_risk: float | None = None
    rumor_stale: float | None = None  # 1 = T4 rumor past the grace period without T0/T1 confirmation
    market_consistency: float | None = None  # +1 consistent, -1 inconsistent, 0 no reaction expected
    debunked: float | None = None  # 1 = official correction/denial exists
    # flags that drive labels rather than the score
    spam_satire: bool = False
    disputed: bool = False  # outlets of comparable rank disagree
    unverifiable: bool = False  # no verification path (anonymous forecast, unnamed sources only)
    missing: list[str] = field(default_factory=list)

    def _v(self, name: str) -> float:
        value = getattr(self, name)
        if value is None:
            if name not in self.missing:
                self.missing.append(name)
            return 0.0
        return float(value)


def score(sv: SignalVector, cfg: VerifyConfig | None = None) -> float:
    """Confidence in (0, 1): sigmoid of the §7.2 logit with the configured weights (bias added, ADR-0006)."""
    w = (cfg or load_verify()).weights
    logit = (
        w.bias
        + w.prior * sv.prior
        + w.log1p_n_independent * math.log1p(max(0, sv.n_independent))
        + w.primary_match * sv._v("primary_match")
        + w.numeric_match * sv._v("numeric_match")
        + w.recycled * sv._v("recycled")
        + w.language_risk * sv._v("language_risk")
        + w.domain_risk * sv._v("domain_risk")
        + w.rumor_stale * sv._v("rumor_stale")
        + w.market_consistency * sv._v("market_consistency")
        + w.debunked * sv._v("debunked")
    )
    return 1.0 / (1.0 + math.exp(-logit))


def decide_label(sv: SignalVector, cfg: VerifyConfig | None = None) -> Label:
    """Rule order from PLAN §7.1/§7.3: quarantine and debunks first, then primary evidence, then source count."""
    if sv.spam_satire:
        return Label.SPAM_SATIRE
    if (sv.debunked or 0) >= 0.5:
        return Label.DEBUNKED
    if (sv.recycled or 0) >= 0.5:
        return Label.RECYCLED
    if (sv.primary_match or 0) >= 0.5 or (sv.numeric_match or 0) >= 0.5:
        return Label.VERIFIED
    if sv.disputed or (sv.primary_match or 0) <= -0.5 or (sv.numeric_match or 0) <= -0.5:
        return Label.DISPUTED
    if sv.n_independent >= 2:
        return Label.CORROBORATED
    if sv.unverifiable or (sv.rumor_stale or 0) >= 0.5:
        return Label.UNVERIFIABLE
    return Label.SINGLE_SOURCE


def report_use(label: Label, cfg: VerifyConfig | None = None) -> str:
    """F (fact), I (interpretation), S (speculation), conflict, notes_only, quarantine — PLAN §7.1 table."""
    return (cfg or load_verify()).labels.report_use[label.value]


def needs_review(impact: float, confidence: float, cfg: VerifyConfig | None = None) -> bool:
    rules = (cfg or load_verify()).rules
    return impact >= float(rules["high_impact"]) and confidence < float(rules["low_confidence"])
