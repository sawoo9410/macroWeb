"""Story selection for extraction (PLAN §0.3: 선별 = 테마 유사도 × 출처 tier; T0 1차 문서 전량; 독립 출처 ≥ 3 은
자동 승격). Theme similarity is keyword overlap with config/themes.yaml until bge-m3 embeddings arrive (Phase 2
후반). S-DATA / S-T4 strata never reach the model (§6.2.1)."""

from __future__ import annotations

import re
import sqlite3
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


@dataclass
class Candidate:
    story: StoryInput
    theme_score: float
    impact: float


def _themes() -> list[tuple[str, list[str]]]:
    cfg = ThemesConfig.model_validate(load_yaml(CONFIG_DIR / "themes.yaml"))
    return [(t.id, [k.lower() for k in t.keywords]) for t in cfg.themes]


def theme_similarity(text: str, themes: list[tuple[str, list[str]]]) -> tuple[float, str | None]:
    """Max over themes of (matched keywords / min(len(keywords), 4)); crude but monotone until embeddings."""
    t = text.lower()
    best, best_id = 0.0, None
    for theme_id, kws in themes:
        hits = sum(1 for k in kws if k and k in t)
        sim = min(1.0, hits / max(1, min(len(kws), 4)))
        if sim > best:
            best, best_id = sim, theme_id
    return best, best_id


def _rep_article(conn: sqlite3.Connection, story_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT a.id, a.source_id, a.title, a.url, a.published_at, a.lang, a.text, a.summary,
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
) -> list[Candidate]:
    """Stories not yet extracted with this prompt version, scored and ordered: T0 documents first (newest),
    then T1/T2 by impact. Also writes stratum/lang/rep_article_id/impact back onto `story` for later stages."""
    cfg = cfg or load_extract()
    now = now or datetime.now(UTC)
    src_by_id = {s.id: s for s in (sources or load_sources().sources)}
    themes = _themes()
    t0_since = (now - timedelta(days=T0_LOOKBACK_DAYS)).isoformat(timespec="seconds")
    t12_since = (now - timedelta(hours=T12_LOOKBACK_HOURS)).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT s.id, s.first_seen, s.n_independent FROM story s
           WHERE NOT EXISTS (SELECT 1 FROM extraction e WHERE e.story_id = s.id AND e.prompt_version = ?)
           ORDER BY s.first_seen DESC LIMIT 4000""",
        (str(prompt_version),),
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
        if len(text) < MIN_TEXT_CHARS and len(rep["title"] or "") < 20:
            continue
        published = rep["published_at"] or row["first_seen"]
        if src.tier == 0:
            if published and published < t0_since:
                continue
        elif published and published < t12_since:
            continue
        sim, theme_id = theme_similarity(f"{rep['title']} {text[:1500]}", themes)
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
        cand = Candidate(story=story, theme_score=sim, impact=impact)
        (t0 if src.tier == 0 else rest).append(cand)
    t0.sort(key=lambda c: c.story.published_at or "", reverse=True)
    rest.sort(key=lambda c: (c.impact, c.story.published_at or ""), reverse=True)
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
    """Entity slug for candidates: lower-case ascii/hangul, hyphens (Phase 3 resolves aliases properly)."""
    s = re.sub(r"[^0-9a-z가-힣]+", "-", name.strip().lower()).strip("-")
    return s[:48] or "unknown"
