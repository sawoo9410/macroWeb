"""L5 graph store (PLAN §8.4–8.5, ADR-0010 v1): seed load, entity resolution, extracted relations → edges with
evidence, expiry by edge family (§0.4), time-sliced reads. Everything is idempotent; nothing is deleted —
merges and expiries leave a trail (entity.merged_into, relation.valid_to/status)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from macroweb.config import load_yaml
from macroweb.extract.persist import alias_index
from macroweb.extract.select import slug
from macroweb.llm.schemas import RELATION_ALIASES, RELATION_TYPES
from macroweb.paths import SEED_DIR

STRUCTURAL = {"supplies_to", "customer_of", "competes_with", "owns_stake", "subsidiary_of", "member_of"}
POWER_INTEREST = {
    "appointed_by",
    "reports_to",
    "regulates",
    "votes_on",
    "lobbies",
    "donates_to",
    "allied_with",
    "opposes",
    "pressures",
    "benefits_from",
    "hurt_by",
    "depends_on",
    "exposed_to",
    "triggers",
    "hedges",
}
DISCOURSE = {"argues", "predicts", "denies", "confirms"}
EXPIRY_DAYS = {
    "structural": 365,
    "power_interest": 90,
    "discourse": 30,
}  # PLAN §0.4; stats/time edges never expire
CONFIRM_STORIES = 3  # PLAN §8.4: candidate → confirmed after 3 stories (or a human)
ACTIVE = ("candidate", "confirmed")


def edge_family(rtype: str) -> str:
    if rtype in STRUCTURAL:
        return "structural"
    if rtype in POWER_INTEREST:
        return "power_interest"
    if rtype in DISCOURSE:
        return "discourse"
    return "other"


def relation_id(src: str, dst: str, rtype: str) -> str:
    return hashlib.sha1(f"{src}|{dst}|{rtype}".encode()).hexdigest()[:16]


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).isoformat(timespec="seconds")


def _json_list(value: str | None) -> list[str]:
    try:
        v = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


# --- entities ----------------------------------------------------------------------------------------------
def upsert_entity(
    conn: sqlite3.Connection,
    *,
    eid: str,
    etype: str,
    name: str,
    aliases: list[str] | None = None,
    country: str | None = None,
    sector: str | None = None,
    profile: dict[str, Any] | None = None,
    status: str = "candidate",
    conflict_of_interest: bool = False,
    valid_from: str | None = None,
) -> bool:
    """Insert or enrich (never downgrade confirmed → candidate, never drop aliases). Returns True if new."""
    row = conn.execute("SELECT * FROM entity WHERE id = ?", (eid,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO entity(id, type, canonical_name, aliases, country, sector, profile_json, status, valid_from, conflict_of_interest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid,
                etype,
                name,
                json.dumps(sorted(set([name, *(aliases or [])])), ensure_ascii=False),
                country,
                sector,
                json.dumps(profile or {}, ensure_ascii=False),
                status,
                valid_from,
                int(conflict_of_interest),
            ),
        )
        return True
    merged_aliases = sorted(set(_json_list(row["aliases"]) + [name, *(aliases or [])]))
    prof = {}
    try:
        prof = json.loads(row["profile_json"] or "{}")
    except json.JSONDecodeError:
        prof = {}
    prof.update({k: v for k, v in (profile or {}).items() if v is not None})
    new_status = "confirmed" if "confirmed" in (row["status"], status) else row["status"]
    conn.execute(
        """UPDATE entity SET type = COALESCE(?, type), canonical_name = COALESCE(canonical_name, ?), aliases = ?,
                  country = COALESCE(?, country), sector = COALESCE(?, sector), profile_json = ?, status = ?,
                  valid_from = COALESCE(valid_from, ?), conflict_of_interest = MAX(conflict_of_interest, ?)
           WHERE id = ?""",
        (
            etype,
            name,
            json.dumps(merged_aliases, ensure_ascii=False),
            country,
            sector,
            json.dumps(prof, ensure_ascii=False),
            new_status,
            valid_from,
            int(conflict_of_interest),
            eid,
        ),
    )
    return False


def resolve_name(conn: sqlite3.Connection, name: str, aliases: dict[str, str] | None = None) -> str | None:
    """Entity id for a surface name: config aliases → stored entity names/aliases → None."""
    if not name:
        return None
    key = name.strip().lower()
    aliases = aliases if aliases is not None else alias_index()
    if key in aliases:
        return aliases[key]
    row = conn.execute(
        "SELECT id FROM entity WHERE lower(canonical_name) = ? AND status != 'merged'", (key,)
    ).fetchone()
    if row:
        return str(row["id"])
    cand = slug(name)
    row = conn.execute("SELECT id, merged_into FROM entity WHERE id = ?", (cand,)).fetchone()
    if row:
        return str(row["merged_into"] or row["id"])
    for r in conn.execute(
        "SELECT id, aliases FROM entity WHERE status != 'merged' AND aliases LIKE ?", (f"%{name.strip()}%",)
    ):
        if key in {a.lower() for a in _json_list(r["aliases"])}:
            return str(r["id"])
    return None


# --- relations ---------------------------------------------------------------------------------------------
@dataclass
class EdgeStats:
    inserted: int = 0
    reinforced: int = 0
    skipped_no_evidence: int = 0
    skipped_unknown_type: int = 0
    skipped_unresolved: int = 0
    entities_new: int = 0


def upsert_edge(
    conn: sqlite3.Connection,
    *,
    src: str,
    dst: str,
    rtype: str,
    sign: int,
    weight: float,
    confidence: float,
    evidence_ids: list[str],
    origin: str,
    story_id: str | None,
    seen_at: str,
    note: str | None = None,
    r: float | None = None,
    lag_days: int | None = None,
) -> str:
    """Create or reinforce an edge. Evidence accumulates (set union); weight follows the story count for extracted
    edges (1 − 0.5^n), is kept as given for seed/computed. Returns 'inserted' | 'reinforced'."""
    rid = relation_id(src, dst, rtype)
    row = conn.execute("SELECT * FROM relation WHERE id = ?", (rid,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO relation(id, src_eid, dst_eid, type, sign, weight, confidence, lag_days, r, valid_from, valid_to,
                                    evidence_ids, last_reinforced, origin, status, note, n_stories)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'candidate', ?, ?)""",
            (
                rid,
                src,
                dst,
                rtype,
                sign,
                round(weight, 4),
                round(confidence, 4),
                lag_days,
                r,
                seen_at,
                json.dumps(sorted(set(evidence_ids)), ensure_ascii=False),
                seen_at,
                origin,
                note,
                1 if story_id else 0,
            ),
        )
        return "inserted"
    ev = sorted(set(_json_list(row["evidence_ids"]) + list(evidence_ids)))
    stories = _json_list(_profile_stories(row["note"]))
    n_stories = int(row["n_stories"] or 0)
    if story_id and story_id not in stories:
        stories.append(story_id)
        n_stories += 1
    new_weight = (
        1 - 0.5 ** max(1, n_stories)
        if origin == "extracted" and row["origin"] != "seed"
        else max(float(row["weight"] or 0), weight)
    )
    new_conf = (
        max(float(row["confidence"] or 0), confidence)
        if origin != "extracted"
        else round((float(row["confidence"] or 0.5) + confidence) / 2, 4)
    )
    status = "confirmed" if (n_stories >= CONFIRM_STORIES or row["status"] == "confirmed") else row["status"]
    if status == "expired" and ev:
        status = "candidate"  # new evidence revives an expired edge
    conn.execute(
        """UPDATE relation SET sign = CASE WHEN ? = 'seed' THEN sign ELSE ? END, weight = ?, confidence = ?,
                  evidence_ids = ?, last_reinforced = MAX(COALESCE(last_reinforced, ''), ?), status = ?, valid_to = NULL,
                  n_stories = ?, note = ?, r = COALESCE(?, r), lag_days = COALESCE(?, lag_days)
           WHERE id = ?""",
        (
            row["origin"],
            sign,
            round(new_weight, 4),
            round(new_conf, 4),
            json.dumps(ev, ensure_ascii=False),
            seen_at,
            status,
            n_stories,
            _note_with_stories(row["note"], stories, note),
            r,
            lag_days,
            rid,
        ),
    )
    return "reinforced"


def _profile_stories(note: str | None) -> str:
    """Story ids ride along in the note as a JSON tail so the schema stays unchanged: '<text> ||stories=[...]'."""
    if note and "||stories=" in note:
        return note.split("||stories=", 1)[1]
    return "[]"


def _note_with_stories(old_note: str | None, stories: list[str], extra: str | None) -> str:
    base = (old_note or "").split("||stories=", 1)[0].strip()
    if extra and extra not in base:
        base = f"{base}; {extra}".strip("; ")
    return f"{base} ||stories={json.dumps(stories)}"


# --- seed --------------------------------------------------------------------------------------------------
@dataclass
class SeedReport:
    entities_new: int = 0
    entities_seen: int = 0
    edges_new: int = 0
    edges_seen: int = 0
    persons: int = 0
    problems: list[str] = field(default_factory=list)


def load_seed(
    conn: sqlite3.Connection, seed_dir: Path = SEED_DIR, *, now: datetime | None = None
) -> SeedReport:
    """seed/entities.yaml + relations.yaml (+ persons/*.yaml profiles) → candidate nodes/edges. Seed edges carry no
    evidence yet (needs_evidence) — Q1 reports them, the pipeline attaches claims as stories arrive."""
    rep = SeedReport()
    stamp = _now_iso(now)
    ents = load_yaml(seed_dir / "entities.yaml").get("entities") or []
    for e in ents:
        extra = {
            k: v
            for k, v in e.items()
            if k not in {"id", "type", "name", "aliases", "country", "sector", "conflict_of_interest"}
        }
        new = upsert_entity(
            conn,
            eid=str(e["id"]),
            etype=str(e["type"]),
            name=str(e["name"]),
            aliases=[str(a) for a in e.get("aliases") or []],
            country=e.get("country"),
            sector=e.get("sector"),
            profile={"seed": True, **extra},
            conflict_of_interest=bool(e.get("conflict_of_interest")),
            valid_from=stamp[:10],
        )
        rep.entities_new += int(new)
        rep.entities_seen += 1
    known = {str(e["id"]) for e in ents}
    rels = load_yaml(seed_dir / "relations.yaml").get("relations") or []
    for r in rels:
        rtype = RELATION_ALIASES.get(str(r["type"]), str(r["type"]))
        if rtype not in RELATION_TYPES:
            rep.problems.append(f"unknown relation type {r['type']} ({r['src']}→{r['dst']})")
            continue
        for end in (r["src"], r["dst"]):
            if (
                end not in known
                and conn.execute("SELECT 1 FROM entity WHERE id = ?", (end,)).fetchone() is None
            ):
                rep.problems.append(f"edge references unknown entity {end}")
        note = str(r.get("note") or "")
        if r.get("needs_evidence"):
            note = f"{note}; needs_evidence".strip("; ")
        res = upsert_edge(
            conn,
            src=str(r["src"]),
            dst=str(r["dst"]),
            rtype=rtype,
            sign=int(r.get("sign", 0)),
            weight=float(r.get("weight", 0.5)),
            confidence=float(r.get("confidence", 0.5)),
            evidence_ids=[],
            origin=str(r.get("origin") or "seed"),
            story_id=None,
            seen_at=stamp,
            note=note or None,
            r=r.get("r"),
            lag_days=r.get("lag_days"),
        )
        rep.edges_new += int(res == "inserted")
        rep.edges_seen += 1
    for p in sorted((seed_dir / "persons").glob("*.yaml")):
        card = load_yaml(p) or {}
        if not card.get("id"):
            continue
        upsert_entity(
            conn,
            eid=str(card["id"]),
            etype="person",
            name=str(card.get("name") or card["id"]),
            profile={"card": {k: v for k, v in card.items() if k != "id"}},
            valid_from=str(card.get("valid_from") or stamp[:10]),
        )
        rep.persons += 1
    conn.commit()
    return rep


# --- extracted relations → edges -----------------------------------------------------------------------------
def update_from_extractions(
    conn: sqlite3.Connection, *, since: str | None = None, now: datetime | None = None, limit: int = 5000
) -> EdgeStats:
    """Read `extraction.result_json` (succeeded) and upsert relation edges. Evidence = the story's persisted claims
    (never empty: a story without claims yields no edge — Q1 invariant). Unknown entity names become candidates."""
    stats = EdgeStats()
    aliases = alias_index()
    stamp = _now_iso(now)
    where = "status = 'succeeded' AND result_json IS NOT NULL"
    params: list[object] = []
    if since:
        where += " AND updated_at >= ?"
        params.append(since)
    rows = conn.execute(
        f"SELECT story_id, result_json, updated_at FROM extraction WHERE {where} ORDER BY updated_at LIMIT ?",  # noqa: S608
        (*params, limit),
    ).fetchall()
    for ex in rows:
        try:
            result = json.loads(ex["result_json"])
        except json.JSONDecodeError:
            continue
        rels = result.get("relations") or []
        if not rels:
            continue
        claims = conn.execute(
            "SELECT id, confidence, first_seen FROM claim WHERE story_id = ? AND status = 'active'",
            (ex["story_id"],),
        ).fetchall()
        if not claims:
            stats.skipped_no_evidence += len(rels)
            continue
        evidence = [c["id"] for c in claims]
        confs = [float(c["confidence"]) for c in claims if c["confidence"] is not None]
        confidence = sum(confs) / len(confs) if confs else 0.5
        seen_at = min((c["first_seen"] for c in claims if c["first_seen"]), default=ex["updated_at"]) or stamp
        ent_types = {e.get("name", "").strip().lower(): e.get("type") for e in result.get("entities") or []}
        for rel in rels:
            rtype = RELATION_ALIASES.get(str(rel.get("type")), str(rel.get("type")))
            if rtype not in RELATION_TYPES:
                stats.skipped_unknown_type += 1
                continue
            ends = []
            for name in (rel.get("src"), rel.get("dst")):
                if not name:
                    break
                eid = resolve_name(conn, str(name), aliases)
                if eid is None:
                    eid = slug(str(name))
                    if upsert_entity(
                        conn,
                        eid=eid,
                        etype=str(ent_types.get(str(name).strip().lower()) or "org"),
                        name=str(name).strip(),
                        profile={"first_story": ex["story_id"]},
                        valid_from=seen_at[:10],
                    ):
                        stats.entities_new += 1
                ends.append(eid)
            if len(ends) != 2 or ends[0] == ends[1]:
                stats.skipped_unresolved += 1
                continue
            res = upsert_edge(
                conn,
                src=ends[0],
                dst=ends[1],
                rtype=rtype,
                sign=int(rel.get("sign") or 0),
                weight=0.5,
                confidence=confidence,
                evidence_ids=evidence,
                origin="extracted",
                story_id=ex["story_id"],
                seen_at=seen_at,
                note=(rel.get("quote_span") or None),
            )
            if res == "inserted":
                stats.inserted += 1
            else:
                stats.reinforced += 1
    conn.commit()
    return stats


# --- resolution & lifecycle ----------------------------------------------------------------------------------
@dataclass
class ResolveReport:
    merged: list[tuple[str, str]] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    counted: int = 0


def merge_entity(conn: sqlite3.Connection, loser: str, winner: str, *, now: datetime | None = None) -> None:
    """Fold `loser` into `winner`: claims, edges (ids recomputed, evidence unioned), aliases; keep the trail."""
    if loser == winner:
        return
    conn.execute("UPDATE claim SET subject_eid = ? WHERE subject_eid = ?", (winner, loser))
    conn.execute("UPDATE claim SET object_eid = ? WHERE object_eid = ?", (winner, loser))
    for col in ("src_eid", "dst_eid"):
        for row in conn.execute(f"SELECT * FROM relation WHERE {col} = ?", (loser,)).fetchall():  # noqa: S608 - column is ours
            src = winner if col == "src_eid" else row["src_eid"]
            dst = winner if col == "dst_eid" else row["dst_eid"]
            if src == dst:
                conn.execute(
                    "UPDATE relation SET status = 'quarantined', note = COALESCE(note, '') || ' self-loop after merge' WHERE id = ?",
                    (row["id"],),
                )
                continue
            upsert_edge(
                conn,
                src=src,
                dst=dst,
                rtype=row["type"],
                sign=int(row["sign"] or 0),
                weight=float(row["weight"] or 0.5),
                confidence=float(row["confidence"] or 0.5),
                evidence_ids=_json_list(row["evidence_ids"]),
                origin=str(row["origin"] or "extracted"),
                story_id=None,
                seen_at=str(row["valid_from"] or _now_iso(now)),
                note=(row["note"] or "").split("||stories=")[0].strip() or None,
                r=row["r"],
                lag_days=row["lag_days"],
            )
            conn.execute(
                "UPDATE relation SET status = 'merged', valid_to = ? WHERE id = ?", (_now_iso(now), row["id"])
            )
    loser_row = conn.execute("SELECT canonical_name, aliases FROM entity WHERE id = ?", (loser,)).fetchone()
    if loser_row:
        upsert_entity(
            conn,
            eid=winner,
            etype="org",
            name=loser_row["canonical_name"] or loser,
            aliases=_json_list(loser_row["aliases"]),
        )
    conn.execute(
        "UPDATE entity SET status = 'merged', merged_into = ?, valid_to = ? WHERE id = ?",
        (winner, _now_iso(now), loser),
    )


def resolve_entities(conn: sqlite3.Connection, *, now: datetime | None = None) -> ResolveReport:
    """(a) exact-alias duplicates → merge into the config canonical id; (b) story counts → candidate→confirmed."""
    rep = ResolveReport()
    aliases = alias_index()
    for row in conn.execute(
        "SELECT id, canonical_name, aliases FROM entity WHERE status IN ('candidate', 'confirmed')"
    ).fetchall():
        names = {(row["canonical_name"] or "").lower(), *(a.lower() for a in _json_list(row["aliases"]))}
        targets = {aliases[n] for n in names if n in aliases and aliases[n] != row["id"]}
        if len(targets) == 1:
            winner = targets.pop()
            if conn.execute("SELECT 1 FROM entity WHERE id = ?", (winner,)).fetchone() is None:
                upsert_entity(conn, eid=winner, etype="org", name=row["canonical_name"] or winner)
            merge_entity(conn, row["id"], winner, now=now)
            rep.merged.append((row["id"], winner))
    counts: dict[str, set[str]] = defaultdict(set)
    for r in conn.execute("SELECT subject_eid, object_eid, story_id FROM claim WHERE status = 'active'"):
        for eid in (r["subject_eid"], r["object_eid"]):
            if eid:
                counts[eid].add(r["story_id"])
    for r in conn.execute(
        "SELECT src_eid, dst_eid, note FROM relation WHERE status IN ('candidate', 'confirmed')"
    ):
        for s in _json_list(_profile_stories(r["note"])):
            counts[r["src_eid"]].add(s)
            counts[r["dst_eid"]].add(s)
    for eid, stories in counts.items():
        row = conn.execute("SELECT status FROM entity WHERE id = ?", (eid,)).fetchone()
        if row is None:
            continue
        conn.execute("UPDATE entity SET n_stories = ? WHERE id = ?", (len(stories), eid))
        rep.counted += 1
        if row["status"] == "candidate" and len(stories) >= CONFIRM_STORIES:
            conn.execute("UPDATE entity SET status = 'confirmed' WHERE id = ?", (eid,))
            rep.promoted.append(eid)
    conn.commit()
    return rep


def expire_edges(conn: sqlite3.Connection, *, now: datetime | None = None) -> int:
    """PLAN §0.4: structural 365 d, power/interest 90 d, discourse 30 d without reinforcement → valid_to + expired."""
    ts = now or datetime.now(UTC)
    n = 0
    for row in conn.execute(
        "SELECT id, type, valid_from, last_reinforced FROM relation WHERE status IN ('candidate', 'confirmed')"
    ).fetchall():
        fam = edge_family(row["type"])
        days = EXPIRY_DAYS.get(fam)
        if not days:
            continue
        last = row["last_reinforced"] or row["valid_from"]
        if not last:
            continue
        try:
            last_dt = datetime.fromisoformat(str(last))
        except ValueError:
            continue
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=UTC)
        if ts - last_dt > timedelta(days=days):
            conn.execute(
                "UPDATE relation SET status = 'expired', valid_to = ? WHERE id = ?",
                ((last_dt + timedelta(days=days)).isoformat(timespec="seconds"), row["id"]),
            )
            n += 1
    conn.commit()
    return n


# --- reads -------------------------------------------------------------------------------------------------
def active_edges(
    conn: sqlite3.Connection, *, as_of: str | None = None, statuses: tuple[str, ...] = ACTIVE
) -> list[sqlite3.Row]:
    """Edges valid at `as_of` (ISO date/datetime; default now). Status filter defaults to candidate+confirmed."""
    ts = as_of or _now_iso()
    marks = ",".join("?" * len(statuses))
    return conn.execute(
        f"""SELECT * FROM relation WHERE status IN ({marks})
            AND (valid_from IS NULL OR valid_from <= ?) AND (valid_to IS NULL OR valid_to > ?)
            ORDER BY weight * confidence DESC""",  # noqa: S608 - placeholders only
        (*statuses, ts + ("T23:59:59" if len(ts) == 10 else ""), ts),
    ).fetchall()


def entity_rows(conn: sqlite3.Connection, ids: set[str] | None = None) -> dict[str, sqlite3.Row]:
    if ids is not None and not ids:
        return {}
    if ids is None:
        rows = conn.execute("SELECT * FROM entity WHERE status != 'merged'").fetchall()
    else:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT * FROM entity WHERE id IN ({marks})", tuple(ids)).fetchall()  # noqa: S608
    return {str(r["id"]): r for r in rows}


def graph_counts(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in conn.execute("SELECT status, COUNT(*) n FROM entity GROUP BY status"):
        out[f"entity_{r['status']}"] = int(r["n"])
    for r in conn.execute("SELECT status, COUNT(*) n FROM relation GROUP BY status"):
        out[f"edge_{r['status']}"] = int(r["n"])
    out["edge_without_evidence"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM relation WHERE status IN ('candidate','confirmed') AND (evidence_ids IS NULL OR evidence_ids = '[]')"
        ).fetchone()[0]
    )
    return out
