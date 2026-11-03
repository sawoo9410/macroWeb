"""Human review decisions (PLAN §7.3): read the `decision` column a person filled in review/<date>.md, close the
queue items, count the outcome against the source (`source_stats.n_confirmed/n_refuted`) and append the
decision to eval/verify/decisions.jsonl (the verifier's learning set). Labels are not changed here — a reject
is a training signal and a credibility hit, not an automatic relabel."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from macroweb.paths import ROOT

DECISIONS_FILE = ROOT / "eval" / "verify" / "decisions.jsonl"
ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*`?([0-9a-f]{16})`?\s*\|(?:[^|]*\|){5}\s*(approve|reject|unsure)\s*\|\s*$",
    re.IGNORECASE,
)


@dataclass
class ReviewApplyResult:
    applied: int = 0
    unknown_claims: list[str] = field(default_factory=list)
    already_decided: list[str] = field(default_factory=list)
    by_decision: dict[str, int] = field(default_factory=dict)
    sources_updated: dict[str, dict[str, int]] = field(default_factory=dict)


def parse_review_md(text: str) -> list[tuple[str, str]]:
    out = []
    for ln in text.splitlines():
        m = ROW.match(ln.strip())
        if m:
            out.append((m.group(1), m.group(2).lower()))
    return out


def apply_review(
    conn: sqlite3.Connection,
    path: Path,
    *,
    by: str = "sangwoo",
    now: datetime | None = None,
    decisions_file: Path | None = None,
) -> ReviewApplyResult:
    now_iso = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    res = ReviewApplyResult()
    rows = parse_review_md(path.read_text(encoding="utf-8"))
    dfile = decisions_file or DECISIONS_FILE
    dfile.parent.mkdir(parents=True, exist_ok=True)
    for cid, decision in rows:
        claim = conn.execute(
            "SELECT id, label, confidence, impact, signals_json, text FROM claim WHERE id = ?", (cid,)
        ).fetchone()
        if claim is None:
            res.unknown_claims.append(cid)
            continue
        cur = conn.execute(
            "UPDATE review_queue SET decision = ?, decided_at = ?, decided_by = ? WHERE claim_id = ? AND decided_at IS NULL",
            (decision, now_iso, by, cid),
        )
        if cur.rowcount == 0:
            res.already_decided.append(cid)
            continue
        res.applied += 1
        res.by_decision[decision] = res.by_decision.get(decision, 0) + 1
        source = json.loads(claim["signals_json"] or "{}").get("source_id")
        if source and decision in ("approve", "reject"):
            col = "n_confirmed" if decision == "approve" else "n_refuted"
            conn.execute(
                f"UPDATE source_stats SET {col} = COALESCE({col}, 0) + 1, updated_at = ? WHERE source_id = ?",  # noqa: S608 - column is ours
                (now_iso, source),
            )
            res.sources_updated.setdefault(source, {"approve": 0, "reject": 0})[decision] += 1
        with dfile.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": now_iso,
                        "claim_id": cid,
                        "decision": decision,
                        "by": by,
                        "label_at_review": claim["label"],
                        "confidence_at_review": claim["confidence"],
                        "impact": claim["impact"],
                        "source_id": source,
                        "verify": json.loads(claim["signals_json"] or "{}").get("verify"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    conn.commit()
    return res


def open_items(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT q.id, q.kind, q.claim_id, q.reason, q.created_at, c.label, c.impact, c.confidence, substr(c.text, 1, 100) AS text
           FROM review_queue q LEFT JOIN claim c ON c.id = q.claim_id WHERE q.decided_at IS NULL ORDER BY q.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
