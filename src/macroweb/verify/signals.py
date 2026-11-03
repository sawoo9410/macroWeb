"""L4 verification v1 — deterministic signals (PLAN §7.2 #1·2·4·5·6) computed from what L1–L3 already stored.
No model calls and no network (ADR-0009). Signal 3 (primary-document trace) is Phase 6, except the degenerate
case where the claim *is* from a tier-0 primary document (evidence.kind = 'primary_doc') → primary_match = 1.
Everything here is explainable: each verdict carries the inputs that produced it (`ClaimVerdict.signals_dict`)."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from macroweb.collect.dedupe import hamming_hex
from macroweb.config import TIER_PRIOR, NumericKey, TolerancesConfig, VerifyConfig, load_verify, load_yaml
from macroweb.paths import CONFIG_DIR
from macroweb.verify.contracts import Label, SignalVector, decide_label, score

# A number is a *change* (skip: the market table holds levels) when the sentence says so.
CHANGE_WORDS = re.compile(
    r"(상승폭|하락폭|오름폭|내림폭|변동폭|\bby\b|basis points?|\bbps?\b|%p|만큼|포인트\s*(상승|하락|오르|내리|올랐|내렸))",
    re.IGNORECASE,
)
# ...and a *level* when it says this; a mismatch is only asserted (-1) for levels, otherwise left undecided.
LEVEL_WORDS = re.compile(
    r"(%로|%에|%를 기록|로\s*(상승|하락|마감|올라|내려|뛰|떨어)|에\s*(마감|거래)|마감했|기록했|수준|종가|"
    r"closed at|\bto\s+\d|\bat\s+\d|stood at|settled at|reached|ended at|finished at)",
    re.IGNORECASE,
)
UNIT_FAMILY: dict[str, str] = {
    "%": "%",
    "퍼센트": "%",
    "percent": "%",
    "pct": "%",
    "bp": "bp",
    "bps": "bp",
    "basis points": "bp",
    "index": "index",
    "pt": "index",
    "p": "index",
    "포인트": "index",
    "point": "index",
    "points": "index",
    "krw": "KRW",
    "원": "KRW",
    "won": "KRW",
    "원/달러": "KRW",
    "usd": "USD",
    "$": "USD",
    "달러": "USD",
    "dollar": "USD",
    "dollars": "USD",
}
CHANGE_UNITS = re.compile(r"(yoy|qoq|mom|wow|전년|전월|전분기|전주|대비)", re.IGNORECASE)
RED_FLAG_CUES: dict[str, tuple[str, ...]] = {
    "sensational_title": ("과장", "sensational", "낚시", "clickbait", "긴급성", "urgency"),
    "no_author": ("저자 없음", "저자없음", "no_author", "byline"),
    "forecast_as_fact": ("전망치", "forecast_as_fact", "확정치", "전망을 확정"),
    "no_source_link": ("외신", "원문 링크", "no_source", "source_link", "원출처"),
    "unsourced_numbers": (
        "숫자 없는",
        "출처 없는 수치",
        "numbers_without_source",
        "단위 혼동",
        "unit_confusion",
        "근거 없는 수치",
    ),
}
SPAM_CUES = ("풍자", "satire", "광고", "advert", "pump", "리딩방", "종목 추천", "spam")
UNVERIFIABLE_TYPES = ("quote", "attribution", "forecast")
MARKET_MAX_STALE_DAYS = 7
VERIFY_VERSION = "v1"


def tolerances() -> TolerancesConfig:
    return TolerancesConfig.model_validate(load_yaml(CONFIG_DIR / "tolerances.yaml"))


def iso_date(value: str | None) -> str | None:
    if not value:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", value.strip())
    return m.group(1) if m else None


def unit_family(unit: str | None) -> str | None:
    """'pt' → index, '원' → KRW, '% YoY' → change (not comparable with a level). Unknown → None."""
    if not unit:
        return None
    u = unit.strip()
    if CHANGE_UNITS.search(u):
        return "change"
    return UNIT_FAMILY.get(u) or UNIT_FAMILY.get(u.lower())


def match_numeric_key(text: str, cfg: VerifyConfig) -> tuple[str | None, NumericKey | None]:
    t = text.lower()
    for key, spec in cfg.numeric_keys.items():
        for p in spec.patterns:
            pl = p.lower()
            if pl.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(pl)}(?![a-z0-9])", t):
                    return key, spec
            elif pl in t:
                return key, spec
    return None, None


@dataclass
class NumericCheck:
    key: str | None = None
    market_value: float | None = None
    market_date: str | None = None
    tolerance: float | None = None
    diff: float | None = None
    match: float | None = None  # 1 within tolerance, -1 clearly outside (level claim), None undecided
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def numeric_check(
    conn: sqlite3.Connection,
    claim: sqlite3.Row,
    *,
    published_at: str | None,
    cfg: VerifyConfig,
    tol: TolerancesConfig,
) -> NumericCheck:
    """Signal 4: compare a numeric *level* claim with the `market` table at the claim's date (or the article's)."""
    nc = NumericCheck()
    if claim["value"] is None:
        nc.note = "no value"
        return nc
    text = " ".join(x for x in (claim["raw_subject"], claim["predicate"], claim["text"]) if x)
    key, spec = match_numeric_key(text, cfg)
    if key is None or spec is None:
        nc.note = "no market key for this subject"
        return nc
    nc.key = key
    fam = unit_family(claim["unit"])
    if fam == "change" or CHANGE_WORDS.search(text):
        nc.note = "change, not a level"
        return nc
    if spec.unit == "%" and fam != "%":
        nc.note = f"unit {claim['unit']!r} is not a percent level"
        return nc
    if spec.unit == "index" and fam not in (None, "index"):
        nc.note = f"unit {claim['unit']!r} is not an index level"
        return nc
    if spec.unit in ("KRW", "USD") and fam != spec.unit:
        nc.note = f"unit {claim['unit']!r} is not {spec.unit}"
        return nc
    target = iso_date(claim["time_ref"]) or iso_date(published_at)
    if target is None:
        nc.note = "no date to compare at"
        return nc
    row = conn.execute(
        "SELECT date, value FROM market WHERE key = ? AND date <= ? ORDER BY date DESC LIMIT 1", (key, target)
    ).fetchone()
    if row is None:
        nc.note = f"no {key} point on or before {target}"
        return nc
    nc.market_value, nc.market_date = float(row["value"]), str(row["date"])
    age = (datetime.fromisoformat(target) - datetime.fromisoformat(nc.market_date)).days
    if age > MARKET_MAX_STALE_DAYS:
        nc.note = f"nearest {key} point is {age} days older than {target}"
        return nc
    t = tol.by_unit.get(spec.unit)
    if t and t.abs is not None:
        nc.tolerance = float(t.abs)
    else:
        rel = t.rel if (t and t.rel is not None) else tol.default_rel
        nc.tolerance = float(rel) * abs(nc.market_value)
    value = float(claim["value"])
    nc.diff = abs(value - nc.market_value)
    if nc.diff <= nc.tolerance:
        nc.match = 1.0
        nc.note = f"{value} vs {key}={nc.market_value} ({nc.market_date}) within ±{nc.tolerance:g}"
    elif nc.diff > 3 * nc.tolerance and LEVEL_WORDS.search(text):
        nc.match = -1.0
        nc.note = f"{value} vs {key}={nc.market_value} ({nc.market_date}) outside 3×tolerance"
    else:
        nc.note = f"{value} vs {key}={nc.market_value} ({nc.market_date}) outside tolerance but level/change ambiguous"
    return nc


def recycled_check(
    conn: sqlite3.Connection, article: sqlite3.Row, *, min_age_days: int, max_hamming: int
) -> tuple[float | None, str]:
    """Signal 5 (v1): a near-identical title (SimHash) published ≥ min_age_days earlier → recycled story.
    Embedding similarity (PLAN: cosine ≥ 0.9) replaces this once bge-m3 lands."""
    sh, pub = article["title_simhash"], article["published_at"]
    if not sh or not pub:
        return None, "no simhash or date"
    try:
        cutoff = (datetime.fromisoformat(pub) - timedelta(days=min_age_days)).isoformat(timespec="seconds")
    except ValueError:
        return None, "unparseable published_at"
    rows = conn.execute(
        """SELECT id, published_at, title_simhash FROM article
           WHERE published_at <= ? AND title_simhash IS NOT NULL AND id != ? AND COALESCE(lang, '') = COALESCE(?, '')
           ORDER BY published_at DESC LIMIT 5000""",
        (cutoff, article["id"], article["lang"]),
    ).fetchall()
    for r in rows:
        if hamming_hex(sh, r["title_simhash"]) <= max_hamming:
            return 1.0, f"near-duplicate title of {r['id']} ({str(r['published_at'])[:10]})"
    return 0.0, "no older near-duplicate title"


def language_proxy(
    claim: sqlite3.Row, signals: dict[str, Any], article: sqlite3.Row | None, tier: int, cfg: VerifyConfig
) -> tuple[float, dict[str, float]]:
    """Signal 6 (v1): weighted deterministic features in place of the LLM rubric. 0 = clean, 1 = risky."""
    lp = cfg.language_proxy
    if lp is None:
        return 0.0, {}
    flags = [str(f).lower() for f in (signals.get("red_flags") or [])]

    def cue(name: str) -> float:
        return 1.0 if any(c in f for f in flags for c in RED_FLAG_CUES[name]) else 0.0

    title = (article["title"] if article else "") or ""
    feats: dict[str, float] = {
        "sensational_title": 1.0
        if re.search(lp.sensational_title_regex, title)
        else cue("sensational_title"),
        "anonymous_source": 1.0 if signals.get("anonymous_source") else 0.0,
        # primary documents have no byline by nature — only penalise news sources
        "no_author": 1.0
        if (tier >= 1 and article is not None and not (article["author"] or "").strip())
        else 0.0,
        "forecast_as_fact": cue("forecast_as_fact"),
        "hedging": min(1.0, len(re.findall(lp.hedging_regex, claim["text"] or "", re.IGNORECASE)) / 3.0),
        "no_source_link": cue("no_source_link"),
        "unsourced_numbers": cue("unsourced_numbers"),
    }
    risk = sum(lp.weights.get(k, 0.0) * v for k, v in feats.items())
    return round(min(1.0, max(0.0, risk)), 4), {k: v for k, v in feats.items() if v}


def source_prior(conn: sqlite3.Connection, source_id: str | None, tier: int) -> float:
    if source_id:
        row = conn.execute(
            "SELECT credibility FROM source_stats WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row and row["credibility"] is not None:
            return float(row["credibility"])
    return TIER_PRIOR.get(tier, 0.5)


def has_primary_evidence(conn: sqlite3.Connection, claim_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM evidence WHERE claim_id = ? AND kind = 'primary_doc' LIMIT 1", (claim_id,)
    ).fetchone()
    return row is not None


@dataclass
class ClaimVerdict:
    claim_id: str
    sv: SignalVector
    confidence: float
    label: Label
    numeric: NumericCheck
    recycled_note: str
    language_feats: dict[str, float]
    decisive: str
    verified_at: str
    missing: list[str] = field(default_factory=list)

    def signals_dict(self) -> dict[str, Any]:
        return {
            "version": VERIFY_VERSION,
            "verified_at": self.verified_at,
            "prior": self.sv.prior,
            "n_independent": self.sv.n_independent,
            "primary_match": self.sv.primary_match,
            "numeric": self.numeric.as_dict(),
            "recycled": self.sv.recycled,
            "recycled_note": self.recycled_note,
            "language_risk": self.sv.language_risk,
            "language_feats": self.language_feats,
            "flags": {
                "spam_satire": self.sv.spam_satire,
                "disputed": self.sv.disputed,
                "unverifiable": self.sv.unverifiable,
            },
            "missing": self.missing,
            "confidence": self.confidence,
            "label": self.label.value,
            "decisive": self.decisive,
        }


def _decisive(sv: SignalVector, nc: NumericCheck, label: Label) -> str:
    parts: list[str] = []
    if label is Label.RECYCLED:
        parts.append("재탕(제목 근사 일치, 90일+)")
    if nc.match == 1.0:
        parts.append(f"수치 일치 {nc.key}")
    elif nc.match == -1.0:
        parts.append(f"수치 불일치 {nc.key}")
    if sv.primary_match == 1.0:
        parts.append("1차 문서 자체")
    if sv.n_independent <= 1 and sv.primary_match is None:
        parts.append("독립 출처 1")
    if (sv.language_risk or 0) >= 0.3:
        parts.append(f"언어 위험 {sv.language_risk:.2f}")
    if sv.unverifiable:
        parts.append("익명 인용·검증 경로 없음")
    if sv.spam_satire:
        parts.append("풍자·광고 의심")
    return " · ".join(parts) or f"prior {sv.prior:.2f}"


def verify_claim(
    conn: sqlite3.Connection,
    claim: sqlite3.Row,
    *,
    n_independent: int,
    article: sqlite3.Row | None,
    source_tier: int,
    now: datetime,
    cfg: VerifyConfig | None = None,
    tol: TolerancesConfig | None = None,
) -> ClaimVerdict:
    cfg = cfg or load_verify()
    tol = tol or tolerances()
    signals = json.loads(claim["signals_json"] or "{}")
    rec_rules = cfg.rules.get("recycled") or {}
    sv = SignalVector()
    sv.prior = source_prior(
        conn, (article["source_id"] if article else None) or signals.get("source_id"), source_tier
    )
    sv.n_independent = max(1, int(n_independent or 1))
    sv.primary_match = 1.0 if has_primary_evidence(conn, claim["id"]) else None
    nc = numeric_check(
        conn, claim, published_at=article["published_at"] if article else None, cfg=cfg, tol=tol
    )
    sv.numeric_match = nc.match
    if article is not None:
        sv.recycled, rec_note = recycled_check(
            conn,
            article,
            min_age_days=int(rec_rules.get("min_age_days", 90)),
            max_hamming=int(rec_rules.get("max_hamming", 3)),
        )
    else:
        sv.recycled, rec_note = None, "no representative article"
    sv.language_risk, feats = language_proxy(claim, signals, article, source_tier, cfg)
    flags = [str(f).lower() for f in (signals.get("red_flags") or [])]
    sv.spam_satire = any(c in f for f in flags for c in SPAM_CUES)
    sv.unverifiable = bool(signals.get("anonymous_source")) and claim["type"] in UNVERIFIABLE_TYPES
    confidence = round(score(sv, cfg), 4)
    label = decide_label(sv, cfg)
    return ClaimVerdict(
        claim_id=claim["id"],
        sv=sv,
        confidence=confidence,
        label=label,
        numeric=nc,
        recycled_note=rec_note,
        language_feats=feats,
        decisive=_decisive(sv, nc, label),
        verified_at=now.isoformat(timespec="seconds"),
        missing=list(sv.missing),
    )
