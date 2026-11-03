"""Write a validated ExtractionResult into claim / evidence / entity (+ story.summary_ko). Ids are deterministic
(sha1 of story + normalised claim text), so re-persisting the same result is a no-op. Relations and cui_bono
stay in `extraction.result_json` until the graph layer (Phase 3) consumes them."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from macroweb.collect.dedupe import title_norm
from macroweb.config import AliasesConfig, load_yaml
from macroweb.extract.contracts import StoryInput
from macroweb.extract.select import slug
from macroweb.llm.schemas import ExtractionResult
from macroweb.paths import CONFIG_DIR

TYPE_WEIGHT = {"numeric": 1.0, "event": 1.0, "forecast": 0.9, "quote": 0.8, "attribution": 0.7}


@dataclass
class PersistStats:
    claims: int = 0
    entities_new: int = 0
    evidence: int = 0


def claim_id(story_id: str, text: str) -> str:
    return hashlib.sha1(f"{story_id}|{title_norm(text)}".encode()).hexdigest()[:16]


def alias_index() -> dict[str, str]:
    """alias (lower) -> canonical entity id, from config/aliases.yaml (Phase 3 adds Wikidata + candidates)."""
    cfg = AliasesConfig.model_validate(load_yaml(CONFIG_DIR / "aliases.yaml"))
    idx: dict[str, str] = {}
    for eid, aliases in cfg.aliases.items():
        idx[eid.lower()] = eid
        for a in aliases:
            idx[str(a).lower()] = eid
    return idx


def ensure_entity(
    conn: sqlite3.Connection, name: str, etype: str, role_hint: str | None, aliases: dict[str, str], now: str
) -> tuple[str, bool]:
    key = name.strip().lower()
    eid = aliases.get(key) or slug(name)
    row = conn.execute("SELECT id FROM entity WHERE id = ?", (eid,)).fetchone()
    if row:
        return eid, False
    conn.execute(
        """INSERT OR IGNORE INTO entity(id, type, canonical_name, aliases, profile_json, status, valid_from)
           VALUES (?, ?, ?, ?, ?, 'candidate', ?)""",
        (
            eid,
            etype,
            name.strip(),
            json.dumps([name.strip()], ensure_ascii=False),
            json.dumps({"role_hint": role_hint}, ensure_ascii=False),
            now,
        ),
    )
    return eid, True


def persist_result(
    conn: sqlite3.Connection,
    story: StoryInput,
    result: ExtractionResult,
    *,
    extracted_by: str,
    now: datetime | None = None,
    aliases: dict[str, str] | None = None,
) -> PersistStats:
    now_iso = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    aliases = aliases if aliases is not None else alias_index()
    stats = PersistStats()
    conn.execute("UPDATE story SET summary_ko = ? WHERE id = ?", (result.summary_ko, story.story_id))

    name_to_eid: dict[str, str] = {}
    for ent in result.entities:
        eid, is_new = ensure_entity(conn, ent.name, ent.type, ent.role_hint, aliases, now_iso)
        name_to_eid[ent.name.strip().lower()] = eid
        stats.entities_new += int(is_new)

    def resolve(name: str | None) -> str | None:
        if not name:
            return None
        key = name.strip().lower()
        return name_to_eid.get(key) or aliases.get(key)

    rep_article_id = str(story.extra.get("rep_article_id") or "") or None
    evidence_kind = "primary_doc" if story.tier == 0 and story.stratum.startswith("S-T0") else "supports"
    base_impact = float(story.impact_hint or 0.5)
    for c in result.claims:
        cid = claim_id(story.story_id, c.text)
        existing = conn.execute("SELECT first_seen FROM claim WHERE id = ?", (cid,)).fetchone()
        first_seen = existing["first_seen"] if existing and existing["first_seen"] else now_iso
        signals = {
            "cited_primary_doc": c.cited_primary_doc,
            "anonymous_source": c.anonymous_source,
            "red_flags": result.red_flags,
            "novelty_hint": result.novelty_hint,
            "theme": story.extra.get("theme"),
            "source_id": story.source_id,
        }
        conn.execute(
            """INSERT OR REPLACE INTO claim(id, story_id, text, type, subject_eid, predicate, object_eid, value, unit, time_ref,
                 confidence, label, impact, signals_json, first_seen, last_updated, status, extracted_by, stratum,
                 raw_subject, raw_object, lang)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                 (SELECT confidence FROM claim WHERE id = ?), (SELECT label FROM claim WHERE id = ?), ?, ?, ?, ?, 'active', ?, ?,
                 ?, ?, ?)""",
            (
                cid,
                story.story_id,
                c.text,
                c.type,
                resolve(c.subject),
                c.predicate,
                resolve(c.object),
                c.value,
                c.unit,
                c.time_ref,
                cid,
                cid,
                round(base_impact * TYPE_WEIGHT.get(c.type, 0.8), 4),
                json.dumps(signals, ensure_ascii=False),
                first_seen,
                now_iso,
                extracted_by,
                story.stratum,
                c.subject,
                c.object,
                story.lang,
            ),
        )
        stats.claims += 1
        if rep_article_id:
            evid = hashlib.sha1(f"{cid}|{rep_article_id}".encode()).hexdigest()[:16]
            cur = conn.execute(
                "INSERT OR IGNORE INTO evidence(id, claim_id, article_id, kind, note) VALUES (?, ?, ?, ?, ?)",
                (evid, cid, rep_article_id, evidence_kind, c.cited_primary_doc),
            )
            stats.evidence += cur.rowcount if cur.rowcount > 0 else 0
    conn.commit()
    return stats
