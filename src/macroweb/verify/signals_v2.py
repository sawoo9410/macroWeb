"""Verification v2 signals that can be computed without new data feeds (PLAN §7.2 #7·9·10·11, §7.4 traps;
ADR-0012). Deterministic and explainable, like v1. Still missing and said so: domain registration age / typosquat
(WHOIS, #7), rumor lifecycle (#8, no T4 ingestion yet), red-team debate (#12)."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from macroweb.collect.dedupe import title_norm
from macroweb.config import VerifyConfig
from macroweb.verify.contracts import SignalVector
from macroweb.verify.signals import iso_date, match_numeric_key

CORRECTION_CUES = re.compile(
    r"(정정|반박|부인|사실무근|해명|오보|철회|denies|denied|denial|correction|corrects|retract|clarif|false report|not true)",
    re.IGNORECASE,
)
MOVE_UP = re.compile(
    r"(급등|상승|올랐|뛰었|강세|반등|surge|jump|rall(y|ied)|rose|gain|climb|higher)", re.IGNORECASE
)
MOVE_DOWN = re.compile(
    r"(급락|하락|내렸|떨어|약세|plunge|fall|fell|drop|slump|declin|sink|lower)", re.IGNORECASE
)
POLICY_THEMES = {
    "us-fiscal",
    "us-midterm-2026",
    "fed-independence",
    "rate-path-dec-hike",
    "iran-hormuz-oil",
    "global-central-banks",
}
FLAT_THRESHOLD = {"pp": 0.02, "%": 0.2}
POLICY_WORDS = re.compile(
    r"(관세|금리|인상|인하|공시|인수|합병|규제|제재|수출통제|tariff|rate (hike|cut)|sanction|merger|acquisition|m&a)",
    re.IGNORECASE,
)


def domain_risk(article: sqlite3.Row | None, known_sources: set[str]) -> tuple[float | None, dict[str, Any]]:
    """#7 v1: no HTTPS or a source outside config/sources.yaml. Registration age and typosquat need WHOIS (later)."""
    if article is None:
        return None, {"note": "no article"}
    feats: dict[str, Any] = {}
    url = article["url"] or ""
    if url.startswith("http://"):
        feats["no_https"] = 1
    if article["source_id"] not in known_sources:
        feats["unknown_source"] = 1
    risk = min(1.0, 0.5 * len(feats))
    feats["note"] = "registration age / typosquat need WHOIS (not implemented)"
    return risk, feats


def correction_watch(
    conn: sqlite3.Connection, claim: sqlite3.Row, article: sqlite3.Row | None, *, days: int = 14
) -> dict[str, Any]:
    """#9: later articles whose title carries a correction/denial cue and names the claim's subject → candidates
    for a human/LLM debunk decision (never auto-DEBUNKED: the cue alone is too weak)."""
    subject = (claim["raw_subject"] or "").strip()
    if not subject or article is None or not article["published_at"]:
        return {"candidates": [], "note": "needs a subject and an article date"}
    try:
        base = datetime.fromisoformat(str(article["published_at"]))
    except ValueError:
        return {"candidates": [], "note": "unparseable article date"}
    start = (base - timedelta(days=1)).isoformat(timespec="seconds")
    end = (base + timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT id, title, source_id, published_at FROM article WHERE published_at >= ? AND published_at <= ? AND id != ? ORDER BY published_at DESC LIMIT 3000",
        (start, end, article["id"]),
    ).fetchall()
    subj = subject.lower()
    cands = [
        {
            "article_id": r["id"],
            "title": r["title"],
            "source_id": r["source_id"],
            "published_at": r["published_at"],
        }
        for r in rows
        if r["title"] and CORRECTION_CUES.search(r["title"]) and subj in r["title"].lower()
    ]
    return {"candidates": cands[:3], "window_days": days}


def market_reaction(
    conn: sqlite3.Connection, claim: sqlite3.Row, article: sqlite3.Row | None, cfg: VerifyConfig
) -> tuple[float | None, dict[str, Any]]:
    """#10: a claim that says an asset moved up/down is checked against the market table on that day:
    +1 consistent, −1 contradicted, 0 no meaningful move; None when the claim is not directional or unmapped."""
    text = " ".join(x for x in (claim["raw_subject"], claim["predicate"], claim["text"]) if x)
    up, down = bool(MOVE_UP.search(text)), bool(MOVE_DOWN.search(text))
    if up == down:
        return None, {"note": "no single directional move claimed"}
    key, _spec = match_numeric_key(text, cfg)
    if key is None:
        return None, {"note": "no market key for the subject"}
    day = iso_date(claim["time_ref"]) or iso_date(article["published_at"] if article else None)
    if day is None:
        return None, {"note": "no date"}
    rows = conn.execute(
        "SELECT date, value FROM market WHERE key = ? AND date <= ? ORDER BY date DESC LIMIT 2", (key, day)
    ).fetchall()
    if len(rows) < 2:
        return None, {"key": key, "note": f"fewer than 2 {key} points on/before {day}"}
    last, prev = float(rows[0]["value"]), float(rows[1]["value"])
    unit = "pp" if key.startswith("UST:") else "%"
    chg = round(last - prev, 4) if unit == "pp" else (round(100 * (last / prev - 1), 2) if prev else 0.0)
    info = {
        "key": key,
        "day": rows[0]["date"],
        "change": chg,
        "unit": unit,
        "claimed": "up" if up else "down",
    }
    if abs(chg) < FLAT_THRESHOLD[unit]:
        return 0.0, {**info, "verdict": "flat"}
    consistent = (chg > 0) == up
    return (1.0 if consistent else -1.0), {**info, "verdict": "consistent" if consistent else "contradicted"}


def generated_content(
    conn: sqlite3.Connection, claim: sqlite3.Row, *, hours: int = 24, min_domains: int = 3
) -> dict[str, Any]:
    """#11 v1: the same normalised sentence showing up from ≥ min_domains different sources within `hours`
    (template/press-release syndication or coordinated posting). Reported as a feature, not a label."""
    if not claim["first_seen"]:
        return {"n_domains": 0, "flag": False}
    try:
        base = datetime.fromisoformat(str(claim["first_seen"]))
    except ValueError:
        return {"n_domains": 0, "flag": False}
    norm = title_norm(claim["text"] or "")
    if len(norm) < 15:
        return {"n_domains": 0, "flag": False, "note": "sentence too short to compare"}
    rows = conn.execute(
        """SELECT text, signals_json FROM claim WHERE id != ? AND first_seen >= ? AND first_seen <= ? AND status = 'active'
           AND LENGTH(text) BETWEEN ? AND ?""",
        (
            claim["id"],
            (base - timedelta(hours=hours)).isoformat(timespec="seconds"),
            (base + timedelta(hours=hours)).isoformat(timespec="seconds"),
            max(1, len(claim["text"] or "") - 20),
            len(claim["text"] or "") + 20,
        ),
    ).fetchall()
    domains = {json.loads(claim["signals_json"] or "{}").get("source_id") or "?"}
    for r in rows:
        if title_norm(r["text"] or "") == norm:
            domains.add(json.loads(r["signals_json"] or "{}").get("source_id") or "?")
    return {"n_domains": len(domains), "flag": len(domains) >= min_domains, "sources": sorted(domains)[:6]}


def apply_traps(
    claim: sqlite3.Row,
    signals: dict[str, Any],
    sv: SignalVector,
    *,
    source_tier: int,
    published_at: str | None,
) -> list[str]:
    """config/traps.yaml patterns that can be decided from what we have. Returns the trap ids that fired and may
    tighten the SignalVector (unverifiable / independence) before scoring."""
    hits: list[str] = []
    flags = [str(f).lower() for f in (signals.get("red_flags") or [])]
    text = (claim["text"] or "").lower()
    if sv.numeric_match == -1.0:
        hits.append("unit_confusion")
    if (
        signals.get("anonymous_source")
        and sv.n_independent < 2
        and (signals.get("theme") in POLICY_THEMES or POLICY_WORDS.search(text))
    ):
        hits.append("anonymous_policy_rumor")
        sv.unverifiable = True
    if source_tier == 3 and claim["type"] == "numeric":
        hits.append("prediction_market_as_fact")
        sv.unverifiable = True
    tr, pub = iso_date(claim["time_ref"]), iso_date(published_at)
    if claim["type"] == "numeric" and tr and pub and tr > pub:
        hits.append("capex_guidance_as_actual")
    if (
        (claim["lang"] == "ko")
        and ("외신" in text or any("외신" in f or "원문 링크" in f for f in flags))
        and not signals.get("cited_primary_doc")
    ):
        hits.append("korean_foreign_roundup")
        sv.n_independent = min(sv.n_independent, 1)
    if (sv.recycled or 0) >= 0.5:
        hits.append("recycled_chart_or_article")
    if sv.spam_satire:
        hits.append("satire_parody")
    return hits


def compute_v2(
    conn: sqlite3.Connection,
    claim: sqlite3.Row,
    article: sqlite3.Row | None,
    sv: SignalVector,
    signals: dict[str, Any],
    *,
    cfg: VerifyConfig,
    source_tier: int,
    known_sources: set[str],
) -> dict[str, Any]:
    """Fill sv.domain_risk / sv.market_consistency, apply traps, and return the explainable v2 block."""
    sv.domain_risk, d_feats = domain_risk(article, known_sources)
    sv.market_consistency, m_info = market_reaction(conn, claim, article, cfg)
    corr = correction_watch(conn, claim, article)
    gen = generated_content(conn, claim)
    if gen.get("flag"):
        sv.language_risk = min(1.0, float(sv.language_risk or 0) + 0.2)
    traps = apply_traps(
        claim, signals, sv, source_tier=source_tier, published_at=article["published_at"] if article else None
    )
    return {
        "domain": d_feats,
        "market_reaction": m_info,
        "correction": corr,
        "generated": gen,
        "traps": traps,
        "not_computed": ["rumor_lifecycle (#8: no T4 feed)", "red_team (#12)", "whois (#7)"],
    }
