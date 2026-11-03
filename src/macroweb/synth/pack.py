"""Weekly data pack (PLAN §10.2 step 1): everything the editorial agents may cite, assembled deterministically from
the DB after the quality gate. Only VERIFIED/CORROBORATED active claims enter the fact slices; quarantined,
superseded and expired items never do. Written to data/weekly/<week>/pack.json plus per-desk slice files so each
analyst reads only its own slice (PLAN §10.1 independence)."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from macroweb.analysis.consistency import cross_asset_check
from macroweb.analysis.regime import snapshot_regime
from macroweb.analysis.thesis import auto_score, list_theses
from macroweb.collect import store
from macroweb.config import CalendarConfig, load_yaml
from macroweb.digest.daily import SNAPSHOT_KEYS, upcoming_events
from macroweb.graph.analysis import hubs, propagate, week_bounds, weekly_diff
from macroweb.graph.store import active_edges, entity_rows
from macroweb.paths import CONFIG_DIR, data_dir
from macroweb.verify.notes import verification_notes

FACT_LABELS = ("VERIFIED", "CORROBORATED")
DESKS: dict[str, tuple[str, ...]] = {  # theme ids (config/themes.yaml) → analyst slice
    "macro": ("rate-path-dec-hike", "dollar-liquidity", "global-central-banks"),
    "policy": ("fed-independence", "us-midterm-2026", "us-fiscal", "iran-hormuz-oil"),
    "semis": ("ai-capex-sustainability", "memory-supercycle"),
    "korea": ("korea-foreign-flows",),
}
TOP_CLAIMS = 100
TOP_THEMES = 10


def weekly_dir(week: str) -> Path:
    return data_dir() / "weekly" / week


def _claim_row(c: sqlite3.Row) -> dict[str, Any]:
    sig = json.loads(c["signals_json"] or "{}")
    return {
        "claim_id": c["id"],
        "text": c["text"],
        "type": c["type"],
        "label": c["label"],
        "confidence": c["confidence"],
        "impact": c["impact"],
        "value": c["value"],
        "unit": c["unit"],
        "time_ref": c["time_ref"],
        "subject_eid": c["subject_eid"],
        "object_eid": c["object_eid"],
        "story_id": c["story_id"],
        "stratum": c["stratum"],
        "lang": c["lang"],
        "theme": sig.get("theme"),
        "source_id": sig.get("source_id"),
        "url": c["url"],
        "published_at": c["published_at"],
        "first_seen": c["first_seen"],
    }


def _market_table(conn: sqlite3.Connection, as_of: str) -> list[dict[str, Any]]:
    out = []
    latest = {r["key"]: r for r in store.market_latest(conn)}
    for key, name, unit in SNAPSHOT_KEYS:
        r = latest.get(key)
        if r is None:
            continue
        series = conn.execute(
            "SELECT date, value FROM market WHERE key = ? AND date <= ? ORDER BY date DESC LIMIT 6",
            (key, as_of),
        ).fetchall()
        chg = None
        if len(series) >= 2:
            first, last = float(series[-1]["value"]), float(series[0]["value"])
            chg = (
                round(last - first, 4)
                if unit == "%"
                else (round(100 * (last / first - 1), 2) if first else None)
            )
        out.append(
            {
                "key": key,
                "name": name,
                "value": float(r["value"]),
                "date": r["date"],
                "unit": unit,
                "change_5d": chg,
                "change_unit": "pp" if unit == "%" else "%",
                "n_days": r["n_days"],
            }
        )
    return out


def _past_theses(conn: sqlite3.Connection, week: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, week, text, horizon_date, probability, status, outcome, brier FROM thesis WHERE week < ? ORDER BY week DESC LIMIT 20",
        (week,),
    ).fetchall()
    return [dict(r) for r in rows]


@dataclass
class PackPaths:
    pack: Path
    slices: dict[str, Path]


def build_pack(conn: sqlite3.Connection, week: str, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    start, end = week_bounds(week)
    as_of = min(end[:10], now.date().isoformat())
    auto_score(conn, today=now.date())  # theses past their horizon get scored (or marked due) before packing
    marks = ",".join("?" * len(FACT_LABELS))
    claims = conn.execute(
        f"""SELECT c.*, a.url, a.published_at FROM claim c
            LEFT JOIN story s ON s.id = c.story_id
            LEFT JOIN article a ON a.id = s.rep_article_id
            WHERE c.status = 'active' AND c.label IN ({marks}) AND c.first_seen >= ? AND c.first_seen < ?
            ORDER BY c.impact DESC, c.confidence DESC, c.first_seen DESC LIMIT ?""",  # noqa: S608 - placeholders only
        (*FACT_LABELS, start, end, TOP_CLAIMS),
    ).fetchall()
    facts = [_claim_row(c) for c in claims]
    label_counts = Counter(
        r["label"]
        for r in conn.execute(
            "SELECT label FROM claim WHERE first_seen >= ? AND first_seen < ? AND status = 'active'",
            (start, end),
        )
    )
    theme_counts: Counter[str] = Counter()
    theme_stories: dict[str, set[str]] = defaultdict(set)
    theme_t0: Counter[str] = Counter()
    for r in conn.execute(
        "SELECT story_id, stratum, signals_json FROM claim WHERE first_seen >= ? AND first_seen < ? AND status = 'active'",
        (start, end),
    ):
        t = json.loads(r["signals_json"] or "{}").get("theme") or "unthemed"
        theme_counts[t] += 1
        theme_stories[t].add(r["story_id"])
        if (r["stratum"] or "").startswith("S-T0"):
            theme_t0[t] += 1
    themes = [
        {
            "theme": t,
            "claims": n,
            "stories": len(theme_stories[t]),
            "t0_share": round(theme_t0[t] / n, 2) if n else 0.0,
        }
        for t, n in theme_counts.most_common(TOP_THEMES)
    ]
    edges = active_edges(conn, as_of=as_of)
    diff = weekly_diff(conn, week, snapshot=False)
    ents = entity_rows(conn, {e["src_eid"] for e in edges} | {e["dst_eid"] for e in edges})
    new_edges = [
        {
            "src": e["src_eid"],
            "dst": e["dst_eid"],
            "type": e["type"],
            "sign": e["sign"],
            "weight": e["weight"],
            "confidence": e["confidence"],
            "evidence": json.loads(e["evidence_ids"] or "[]")[:5],
            "n_evidence": len(json.loads(e["evidence_ids"] or "[]")),
            "origin": e["origin"],
        }
        for e in diff.new_edges[:30]
    ]
    cal = CalendarConfig.model_validate(load_yaml(CONFIG_DIR / "calendar.yaml"))
    horizon = date.fromisoformat(as_of) + timedelta(days=14)
    shocks: list[dict[str, Any]] = []
    for ev in cal.events:
        try:
            d = date.fromisoformat(ev.date)
        except ValueError:
            continue
        if date.fromisoformat(as_of) <= d <= horizon and ev.id in ents:
            for sign in (1, -1):
                effects = propagate(edges, ev.id, sign=sign, magnitude=1.0, floor=0.02)[:10]
                if effects:
                    shocks.append({"shock": ev.id, "sign": sign, "effects": [x.as_dict() for x in effects]})
    review_rows = conn.execute(
        """SELECT q.kind, q.claim_id, q.reason, c.text FROM review_queue q LEFT JOIN claim c ON c.id = q.claim_id
           WHERE q.decided_at IS NULL ORDER BY q.id DESC LIMIT 10"""
    ).fetchall()
    quality = conn.execute("SELECT * FROM quality_run WHERE week = ?", (week,)).fetchone()
    pack: dict[str, Any] = {
        "week": week,
        "generated_at": now.isoformat(timespec="seconds"),
        "date_range": f"{start[:10]} ~ {(date.fromisoformat(end[:10]) - timedelta(days=1)).isoformat()}",
        "as_of": as_of,
        "quality": {
            "lights": json.loads(quality["status_json"]).get("lights")
            if quality and quality["status_json"]
            else None,
            "q1_fail": quality["q1_fail"] if quality else None,
            "q6": json.loads(quality["q6_json"]) if quality and quality["q6_json"] else None,
            "note": None
            if quality
            else "quality run missing for this week — run `macroweb quality run` first",
        },
        "label_counts": dict(label_counts),
        "themes": themes,
        "claims": facts,
        "graph": {
            "diff": diff.summary(),
            "new_edges": new_edges,
            "hubs": [
                {
                    "entity": n,
                    "pagerank": round(s, 4),
                    "name": (ents[n]["canonical_name"] if n in ents else n),
                }
                for n, s in hubs(edges, top=10)
            ],
            "shocks": shocks,
        },
        "market": _market_table(conn, as_of),
        "calendar_14d": upcoming_events(as_of),
        "review_open": [dict(r) for r in review_rows],
        "past_theses": _past_theses(conn, week),
        "regime": snapshot_regime(conn, week, as_of=as_of).as_dict(),
        "consistency": cross_asset_check(
            conn,
            [(s["shock"], s["sign"]) for s in shocks]
            or [(ev.id, 1) for ev in cal.events if ev.id in ents][:3],
            as_of=as_of,
        ).as_dict(),
        "verification_notes": verification_notes(conn, week),
        "theses_open": [t.as_dict() for t in list_theses(conn, status="open")][:10],
        "theses_due": [t.as_dict() for t in list_theses(conn, status="due")][:10],
        "rules": {
            "fact_labels": list(FACT_LABELS),
            "cite": "[F] 문장마다 [claim_id] 각주 — 이 pack 의 claims 밖의 사실은 쓰지 않는다",
            "forbidden": "매수·매도·비중 조절·헤지 지시 금지 (CLAUDE.md 불변 규칙 3)",
        },
    }
    slices: dict[str, Any] = {}
    for desk, theme_ids in DESKS.items():
        picked = [c for c in facts if c["theme"] in theme_ids]
        if desk == "korea":
            picked += [c for c in facts if c["lang"] == "ko" and c not in picked]
        slices[desk] = {
            "week": week,
            "desk": desk,
            "themes": [t for t in themes if t["theme"] in theme_ids],
            "claims": picked[:40],
            "market": pack["market"],
            "calendar_14d": pack["calendar_14d"],
            "rules": pack["rules"],
        }
    slices["cartographer"] = {
        "week": week,
        "graph": pack["graph"],
        "market": pack["market"],
        "rules": pack["rules"],
    }
    slices["historian"] = {
        "week": week,
        "themes": themes,
        "one_line_facts": [c["text"] for c in facts[:15]],
        "market": pack["market"],
        "rules": pack["rules"],
    }
    pack["slices"] = sorted(slices)
    pack["_slices"] = slices
    return pack


def write_pack(
    conn: sqlite3.Connection, week: str, *, now: datetime | None = None, out_dir: Path | None = None
) -> PackPaths:
    pack = build_pack(conn, week, now=now)
    slices = pack.pop("_slices")
    d = out_dir or weekly_dir(week)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "pack.json"
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    sdir = d / "slices"
    sdir.mkdir(exist_ok=True)
    written = {}
    for name, body in slices.items():
        p = sdir / f"{name}.json"
        p.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        written[name] = p
    return PackPaths(pack=path, slices=written)
