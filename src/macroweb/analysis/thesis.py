"""Thesis ledger v1 (PLAN §9.7): "[기간]까지 [관측 가능한 사건] 확률 p. 틀렸다면 [신호]가 보인다." Theses live in
the `thesis` table; outcomes are entered by a person (`thesis score`) or, when the thesis names a market key with
a threshold (`auto_json`), scored automatically once the horizon has passed. Brier = (p − outcome)²."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b}


def thesis_id(week: str, text: str) -> str:
    return "th-" + hashlib.sha1(f"{week}|{text.strip()}".encode()).hexdigest()[:10]


@dataclass
class Thesis:
    id: str
    week: str
    text: str
    horizon_date: str
    probability: float
    falsifier: str | None
    status: str
    outcome: int | None
    brier: float | None
    claim_ids: list[str]
    auto: dict[str, Any] | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> Thesis:
        return cls(
            id=r["id"],
            week=r["week"],
            text=r["text"],
            horizon_date=r["horizon_date"],
            probability=float(r["probability"] or 0),
            falsifier=r["falsifier"],
            status=r["status"],
            outcome=r["outcome"],
            brier=r["brier"],
            claim_ids=json.loads(r["claim_ids"] or "[]"),
            auto=json.loads(r["auto_json"]) if r["auto_json"] else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def add_thesis(
    conn: sqlite3.Connection,
    *,
    week: str,
    text: str,
    horizon_date: str,
    probability: float,
    falsifier: str | None = None,
    claim_ids: list[str] | None = None,
    auto: dict[str, Any] | None = None,
    debate_path: str | None = None,
) -> Thesis:
    """Idempotent on (week, text). `auto` = {"market_key": "UST:2Y", "op": ">=", "threshold": 4.5} scores itself."""
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    date.fromisoformat(horizon_date)
    if auto:
        if auto.get("op") not in OPS or "market_key" not in auto or "threshold" not in auto:
            raise ValueError("auto needs market_key, op in >=,<=,>,< and threshold")
    tid = thesis_id(week, text)
    conn.execute(
        """INSERT INTO thesis(id, week, text, horizon_date, probability, falsifier, status, debate_path, claim_ids, auto_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET horizon_date = excluded.horizon_date, probability = excluded.probability,
             falsifier = excluded.falsifier, debate_path = COALESCE(excluded.debate_path, thesis.debate_path),
             claim_ids = excluded.claim_ids, auto_json = COALESCE(excluded.auto_json, thesis.auto_json)""",
        (
            tid,
            week,
            text.strip(),
            horizon_date,
            probability,
            falsifier,
            debate_path,
            json.dumps(sorted(set(claim_ids or [])), ensure_ascii=False),
            json.dumps(auto, ensure_ascii=False) if auto else None,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return get_thesis(conn, tid)


def get_thesis(conn: sqlite3.Connection, tid: str) -> Thesis:
    row = conn.execute("SELECT * FROM thesis WHERE id = ?", (tid,)).fetchone()
    if row is None:
        raise KeyError(tid)
    return Thesis.from_row(row)


def list_theses(
    conn: sqlite3.Connection, *, week: str | None = None, status: str | None = None
) -> list[Thesis]:
    where, params = [], []
    if week:
        where.append("week = ?")
        params.append(week)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = (
        "SELECT * FROM thesis"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY week DESC, horizon_date"
    )
    return [Thesis.from_row(r) for r in conn.execute(sql, params).fetchall()]


def score_thesis(conn: sqlite3.Connection, tid: str, outcome: int, *, by: str = "human") -> Thesis:
    if outcome not in (0, 1):
        raise ValueError("outcome must be 0 or 1")
    t = get_thesis(conn, tid)
    brier = round((t.probability - outcome) ** 2, 4)
    conn.execute(
        "UPDATE thesis SET outcome = ?, brier = ?, status = ?, scored_at = ? WHERE id = ?",
        (outcome, brier, f"scored_{by}", datetime.now(UTC).isoformat(timespec="seconds"), tid),
    )
    conn.commit()
    return get_thesis(conn, tid)


def auto_score(conn: sqlite3.Connection, *, today: date | None = None) -> dict[str, list[str]]:
    """Open theses past their horizon: score those with `auto_json` against the market table, mark the rest 'due'."""
    today = today or datetime.now(UTC).date()
    out: dict[str, list[str]] = {"scored": [], "due": [], "no_data": []}
    for t in list_theses(conn, status="open"):
        if date.fromisoformat(t.horizon_date) > today:
            continue
        if not t.auto:
            conn.execute("UPDATE thesis SET status = 'due' WHERE id = ?", (t.id,))
            out["due"].append(t.id)
            continue
        row = conn.execute(
            "SELECT value, date FROM market WHERE key = ? AND date <= ? ORDER BY date DESC LIMIT 1",
            (t.auto["market_key"], t.horizon_date),
        ).fetchone()
        if row is None:
            out["no_data"].append(t.id)
            continue
        hit = OPS[t.auto["op"]](float(row["value"]), float(t.auto["threshold"]))
        score_thesis(conn, t.id, int(hit), by="auto")
        out["scored"].append(t.id)
    conn.commit()
    return out


def board_rows(theses: list[Thesis]) -> str:
    """Markdown rows for the report's 논제 보드 table."""
    lines = []
    for i, t in enumerate(theses, 1):
        lines.append(f"| {i} | {t.text} | {t.horizon_date} | {t.probability:.2f} | {t.falsifier or '-'} |")
    return "\n".join(lines)


def calibration(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT probability, outcome, brier FROM thesis WHERE outcome IS NOT NULL").fetchall()
    if not rows:
        return {"n": 0, "mean_brier": None, "buckets": []}
    buckets: dict[str, list[int]] = {}
    for r in rows:
        b = f"{int(float(r['probability']) * 10) * 10:02d}-{int(float(r['probability']) * 10) * 10 + 10:02d}"
        buckets.setdefault(b, []).append(int(r["outcome"]))
    return {
        "n": len(rows),
        "mean_brier": round(sum(float(r["brier"]) for r in rows) / len(rows), 4),
        "buckets": [
            {"range": k, "n": len(v), "hit_rate": round(sum(v) / len(v), 3)}
            for k, v in sorted(buckets.items())
        ],
    }
