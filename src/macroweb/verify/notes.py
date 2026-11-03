"""Verification notes (PLAN §7.6): the week's filtered claims and *which signal* caught them — the training
section of the report. Reads claim.signals_json["verify"] written by the verifier; never invents a reason."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from macroweb.graph.analysis import week_bounds

FILTERED = ("DEBUNKED", "RECYCLED", "SPAM_SATIRE", "DISPUTED", "UNVERIFIABLE")
LABEL_KO = {
    "DEBUNKED": "반박됨",
    "RECYCLED": "재탕",
    "SPAM_SATIRE": "풍자·광고",
    "DISPUTED": "수치 불일치",
    "UNVERIFIABLE": "검증 불가",
}


def verification_notes(conn: sqlite3.Connection, week: str, *, limit: int = 3) -> str:
    start, end = week_bounds(week)
    marks = ",".join("?" * len(FILTERED))
    rows = conn.execute(
        f"""SELECT id, label, text, impact, confidence, signals_json FROM claim
            WHERE first_seen >= ? AND first_seen < ? AND label IN ({marks})
            ORDER BY impact DESC, confidence ASC LIMIT ?""",  # noqa: S608 - placeholders only
        (start, end, *FILTERED, limit),
    ).fetchall()
    dist = Counter(
        r["label"]
        for r in conn.execute(
            "SELECT label FROM claim WHERE first_seen >= ? AND first_seen < ? AND label IS NOT NULL",
            (start, end),
        )
    )
    lines = []
    for r in rows:
        v = json.loads(r["signals_json"] or "{}").get("verify", {})
        decisive = v.get("decisive") or "-"
        traps = (v.get("v2") or {}).get("traps") or []
        src = json.loads(r["signals_json"] or "{}").get("source_id") or "-"
        text = (r["text"] or "").replace("\n", " ")
        text = text if len(text) <= 100 else text[:97] + "…"
        extra = f" · 함정: {', '.join(traps)}" if traps else ""
        lines.append(
            f"- [{LABEL_KO.get(r['label'], r['label'])}] {text} — 걸러낸 신호: {decisive}{extra} ({src}, `{r['id']}`)"
        )
    if not lines:
        lines.append("- 이번 주 걸러낸 claim 없음")
    summary = " · ".join(f"{k} {v}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1])) or "라벨 없음"
    lines.append(f"- 이번 주 라벨 분포: {summary}")
    return "\n".join(lines)
