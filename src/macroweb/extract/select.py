"""Story selection for extraction (PLAN §0.3: 선별 = 테마 유사도 × 출처 tier; T0 1차 문서 전량; 독립 출처 ≥ 3 은
자동 승격). Theme similarity is keyword overlap with config/themes.yaml until bge-m3 embeddings arrive (Phase 2
후반). S-DATA / S-T4 strata never reach the model (§6.2.1)."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from macroweb.config import (
    TIER_PRIOR,
    ExtractConfig,
    Source,
    Stratum,
    ThemesConfig,
    load_extract,
    load_sources,
    load_yaml,
)
from macroweb.extract.contracts import StoryInput
from macroweb.paths import CONFIG_DIR

LLM_STRATA: frozenset[str] = frozenset({"S-T0-STMT", "S-T0-LONG", "S-T1", "S-T1-KO", "S-T2"})
MIN_TEXT_CHARS = 60
T0_LOOKBACK_DAYS = (
    120  # older primary documents are history, not news; t0diff reads them directly when pairing
)
T12_LOOKBACK_HOURS = 72
# Transient failures (harness/network) are retried; schema failures are terminal after the escalation ladder.
RETRY_MAX_ATTEMPTS = 2
RETRY_COOLDOWN = timedelta(minutes=30)
INFLIGHT_STALE = timedelta(hours=6)  # a 'submitted' row older than this belongs to a crashed run

# A story is blocked for a prompt version while any of its extraction rows is final (succeeded/quarantined),
# in flight, or failed in a way that must not be retried automatically.
_BLOCKED_SQL = """EXISTS (
    SELECT 1 FROM extraction e WHERE e.story_id = s.id AND e.prompt_version = ?
      AND (e.status IN ('succeeded', 'quarantined')
           OR (e.status IN ('submitted', 'queued') AND e.updated_at > ?)
           OR (e.status = 'failed' AND (e.error LIKE 'schema%' OR e.attempts >= ? OR e.updated_at > ?))))"""


@dataclass
class Candidate:
    story: StoryInput
    theme_score: float
    impact: float
    keyword_hits: int = 0  # distinct theme keywords found anywhere (tie-break, never a gate on its own)


def _themes() -> list[tuple[str, list[str]]]:
    cfg = ThemesConfig.model_validate(load_yaml(CONFIG_DIR / "themes.yaml"))
    return [(t.id, [k.lower() for k in t.keywords]) for t in cfg.themes]


def _keyword_hit(keyword: str, text: str) -> bool:
    """Latin keywords match whole words only (`tga` must not fire inside "mortgage", `qt` inside "qtr");
    Hangul keywords stay substrings because particles attach without spaces (금리를, 환율이)."""
    if keyword.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def theme_similarity(text: str, themes: list[tuple[str, list[str]]]) -> tuple[float, str | None]:
    """Max over themes of (matched keywords / min(len(keywords), 4)); crude but monotone until embeddings."""
    t = text.lower()
    best, best_id = 0.0, None
    for theme_id, kws in themes:
        hits = sum(1 for k in kws if k and _keyword_hit(k, t))
        sim = min(1.0, hits / max(1, min(len(kws), 4)))
        if sim > best:
            best, best_id = sim, theme_id
    return best, best_id


def keyword_hits(text: str, themes: list[tuple[str, list[str]]]) -> int:
    t = text.lower()
    return len({k for _, kws in themes for k in kws if k and _keyword_hit(k, t)})


def _rep_article(conn: sqlite3.Connection, story_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT a.id, a.source_id, a.title, a.url, a.published_at, a.lang, a.text, a.summary, a.body_status,
                  COALESCE(LENGTH(a.text), 0) AS tlen, COALESCE(LENGTH(a.summary), 0) AS slen
           FROM story_article sa JOIN article a ON a.id = sa.article_id
           WHERE sa.story_id = ? ORDER BY sa.is_syndicated, tlen DESC, slen DESC, a.fetched_at LIMIT 1""",
        (story_id,),
    ).fetchone()


def select_candidates(
    conn: sqlite3.Connection,
    *,
    prompt_version: int,
    limit: int,
    cfg: ExtractConfig | None = None,
    sources: list[Source] | None = None,
    now: datetime | None = None,
    only: Iterable[str] | None = None,
    force: bool = False,
) -> list[Candidate]:
    """Stories not yet extracted with this prompt version, scored and ordered: T0 documents first (newest),
    then T1/T2 by impact. Also writes stratum/lang/rep_article_id/impact back onto `story` for later stages.
    Transient failures come back after RETRY_COOLDOWN up to RETRY_MAX_ATTEMPTS; `only` restricts to given story
    ids and `force` ignores the ledger for them (operator re-run; claim ids are content-addressed, so idempotent)."""
    cfg = cfg or load_extract()
    now = now or datetime.now(UTC)
    src_by_id = {s.id: s for s in (sources or load_sources().sources)}
    themes = _themes()
    t0_since = (now - timedelta(days=T0_LOOKBACK_DAYS)).isoformat(timespec="seconds")
    t12_since = (now - timedelta(hours=T12_LOOKBACK_HOURS)).isoformat(timespec="seconds")
    only_ids = sorted(set(only)) if only is not None else None
    clauses: list[str] = []
    params: list[object] = []
    if not force:
        clauses.append(f"NOT {_BLOCKED_SQL}")
        params += [
            str(prompt_version),
            (now - INFLIGHT_STALE).isoformat(timespec="seconds"),
            RETRY_MAX_ATTEMPTS,
            (now - RETRY_COOLDOWN).isoformat(timespec="seconds"),
        ]
    if only_ids is not None:
        clauses.append(f"s.id IN ({','.join('?' * len(only_ids))})" if only_ids else "0")
        params += only_ids
    where = " AND ".join(clauses) or "1"
    rows = conn.execute(
        f"SELECT s.id, s.first_seen, s.n_independent FROM story s WHERE {where} "  # noqa: S608 - placeholders only
        "ORDER BY s.first_seen DESC LIMIT 4000",
        params,
    ).fetchall()
    t0: list[Candidate] = []
    rest: list[Candidate] = []
    for row in rows:
        rep = _rep_article(conn, row["id"])
        if rep is None:
            continue
        src = src_by_id.get(rep["source_id"])
        if src is None or not src.stratum or src.stratum not in LLM_STRATA:
            continue
        text = rep["text"] or rep["summary"] or ""
        if len(text) < MIN_TEXT_CHARS:
            # no usable text yet: keep only if the body can still be fetched (extract.bodies.ensure_bodies), else skip
            if not (src.fetch_body and not src.paywall and rep["body_status"] in (None, "none")):
                continue
        published = rep["published_at"] or row["first_seen"]
        if src.tier == 0:
            if published and published < t0_since:
                continue
        elif published and published < t12_since:
            continue
        probe_text = f"{rep['title']} {text[:1500]}"
        sim, theme_id = theme_similarity(probe_text, themes)
        hits = keyword_hits(probe_text, themes)
        n_ind = int(row["n_independent"] or 1)
        policy = src.select_policy or "theme"
        if policy == "title_regex":
            if not (src.select_regex and re.search(src.select_regex, rep["title"] or "", re.IGNORECASE)):
                continue
        elif policy == "theme":
            if sim < cfg.selection.min_theme_score and n_ind < cfg.selection.min_independent_to_force:
                continue
        impact = cfg.selection.theme_weight * sim + cfg.selection.tier_weight * TIER_PRIOR[src.tier]
        if n_ind >= cfg.selection.min_independent_to_force:
            impact = max(impact, 0.9)
        stratum: Stratum = src.stratum
        story = StoryInput(
            story_id=row["id"],
            source_id=src.id,
            tier=src.tier,
            stratum=stratum,
            title=rep["title"] or "",
            text=text,
            url=rep["url"],
            published_at=published,
            lang=rep["lang"] or src.lang,
            n_independent=n_ind,
            impact_hint=impact,
            extra={"theme": theme_id, "rep_article_id": rep["id"]},
        )
        conn.execute(
            "UPDATE story SET stratum = ?, lang = ?, rep_article_id = ?, impact = ? WHERE id = ?",
            (stratum, story.lang, rep["id"], round(impact, 4), row["id"]),
        )
        cand = Candidate(story=story, theme_score=sim, impact=impact, keyword_hits=hits)
        (t0 if src.tier == 0 else rest).append(cand)
    t0.sort(key=lambda c: c.story.published_at or "", reverse=True)
    rest.sort(key=lambda c: (c.impact, c.keyword_hits, c.story.published_at or ""), reverse=True)
    limit = max(0, limit)
    t0_cap = limit if not rest else max(1, int(round(limit * cfg.selection.t0_share)))
    chosen = t0[:t0_cap] + rest
    chosen = chosen[:limit] if len(t0) >= t0_cap else (t0 + rest)[:limit]
    stamp = now.isoformat(timespec="seconds")
    for c in chosen:
        conn.execute(
            "UPDATE story SET selected_at = COALESCE(selected_at, ?) WHERE id = ?", (stamp, c.story.story_id)
        )
    conn.commit()
    return chosen


def slug(name: str) -> str:
    """Entity slug for candidates: lower-case ascii/hangul, hyphens; Latin diacritics folded (António → antonio).
    Phase 3 resolves aliases properly."""
    folded = unicodedata.normalize("NFKD", name.strip().lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    s = re.sub(r"[^0-9a-z가-힣]+", "-", unicodedata.normalize("NFC", folded)).strip("-")
    return s[:48] or "unknown"
