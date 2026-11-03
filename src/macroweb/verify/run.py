"""L4 verify job (Phase 2, ADR-0009): label active claims with the v1 signals, keep `claim.signals_json["verify"]`
explainable, feed the human review queue (PLAN §7.3: impact ≥ 0.7 and conf < 0.5) and render review/<date>.md.
Idempotent: the same inputs give the same labels, and an open queue row is never duplicated."""

from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from macroweb.config import KeyPersonsConfig, TierName, VerifyConfig, load_models, load_verify, load_yaml
from macroweb.llm.router import ModelRouter
from macroweb.paths import CONFIG_DIR, ROOT, review_dir
from macroweb.verify.contracts import needs_review
from macroweb.verify.signals import ClaimVerdict, tolerances, verify_claim

KST = ZoneInfo("Asia/Seoul")
REVIEW_KIND = "low_conf_high_impact"
TEMPLATE = ROOT / "review" / "_template.md"


@dataclass
class VerifyReport:
    considered: int = 0
    updated: int = 0
    labels: Counter[str] = field(default_factory=Counter)
    review_added: int = 0
    review_open: int = 0
    review_md: Path | None = None
    escalations_queued: int = 0
    debunk_candidates: int = 0
    elapsed_s: float = 0.0

    def render(self) -> str:
        dist = " ".join(f"{k}={v}" for k, v in sorted(self.labels.items(), key=lambda kv: -kv[1]))
        lines = [
            f"verify considered={self.considered} updated={self.updated} review +{self.review_added} (open {self.review_open}) "
            f"escalations queued {self.escalations_queued} {self.elapsed_s:.1f}s",
            f"labels: {dist or '-'}",
        ]
        if self.review_md:
            lines.append(f"review: {self.review_md}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        return {
            "considered": self.considered,
            "updated": self.updated,
            "labels": dict(self.labels),
            "review_added": self.review_added,
            "review_open": self.review_open,
            "review_md": str(self.review_md) if self.review_md else None,
            "elapsed_s": round(self.elapsed_s, 2),
        }


def _claims_to_verify(
    conn: sqlite3.Connection,
    *,
    since_hours: int,
    story_ids: list[str] | None,
    relabel: bool,
    now: datetime,
) -> list[sqlite3.Row]:
    where = ["c.status = 'active'"]
    params: list[object] = []
    if story_ids:
        where.append(f"c.story_id IN ({','.join('?' * len(story_ids))})")
        params += list(story_ids)
    if not relabel:
        since = (now - timedelta(hours=since_hours)).isoformat(timespec="seconds")
        where.append("(c.label IS NULL OR c.last_updated >= ?)")
        params.append(since)
    return conn.execute(
        f"""SELECT c.*, s.n_independent AS story_n_independent, s.rep_article_id, s.impact AS story_impact
            FROM claim c JOIN story s ON s.id = c.story_id
            WHERE {" AND ".join(where)} ORDER BY c.story_id, c.rowid""",  # noqa: S608 - placeholders only
        params,
    ).fetchall()


def _article_for(conn: sqlite3.Connection, claim: sqlite3.Row) -> sqlite3.Row | None:
    """The story's representative article (what the extractor read), else any evidence article."""
    sql = "SELECT a.*, src.tier AS source_tier FROM article a LEFT JOIN source src ON src.id = a.source_id WHERE a.id = ?"
    if claim["rep_article_id"]:
        row = conn.execute(sql, (claim["rep_article_id"],)).fetchone()
        if row:
            return row
    ev = conn.execute("SELECT article_id FROM evidence WHERE claim_id = ? LIMIT 1", (claim["id"],)).fetchone()
    return conn.execute(sql, (ev["article_id"],)).fetchone() if ev else None


def _merge_signals(existing: str | None, verdict: ClaimVerdict) -> str:
    base = json.loads(existing or "{}")
    base["verify"] = verdict.signals_dict()
    return json.dumps(base, ensure_ascii=False)


def _enqueue_review(
    conn: sqlite3.Connection, claim: sqlite3.Row, verdict: ClaimVerdict, now_iso: str
) -> bool:
    open_row = conn.execute(
        "SELECT 1 FROM review_queue WHERE claim_id = ? AND kind = ? AND decided_at IS NULL LIMIT 1",
        (claim["id"], REVIEW_KIND),
    ).fetchone()
    if open_row:
        return False
    conn.execute(
        "INSERT INTO review_queue(kind, claim_id, story_id, reason, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            REVIEW_KIND,
            claim["id"],
            claim["story_id"],
            verdict.decisive,
            json.dumps(
                {"label": verdict.label.value, "confidence": verdict.confidence, "impact": claim["impact"]},
                ensure_ascii=False,
            ),
            now_iso,
        ),
    )
    return True


TIER_ORDER: tuple[TierName, ...] = ("small", "mid", "large")


def key_person_names() -> set[str]:
    try:
        cfg = KeyPersonsConfig.model_validate(load_yaml(CONFIG_DIR / "key_persons.yaml"))
    except Exception:
        return set()
    return {p.name.lower() for p in cfg.persons if p.name}


def escalation_reason(
    claim: sqlite3.Row, verdict: ClaimVerdict, impact: float, key_names: set[str]
) -> str | None:
    """PLAN §6.2.2 rules 2–4 (rule 1 lives in the runner, rule 5 needs the T4 path)."""
    if verdict.numeric.match == -1.0:
        return "numeric_mismatch"
    if impact >= 0.7 and verdict.label.value == "DISPUTED":
        return "disputed_high_impact"
    if claim["type"] in ("quote", "attribution") and key_names:
        subject = ((claim["raw_subject"] or "") + " " + (claim["text"] or "")).lower()
        if any(name in subject for name in key_names):
            return "key_person_quote"
    return None


def _story_tier(conn: sqlite3.Connection, story_id: str) -> TierName | None:
    rows = conn.execute(
        "SELECT model_tier, status FROM extraction WHERE story_id = ? ORDER BY updated_at DESC", (story_id,)
    ).fetchall()
    used: list[TierName] = [
        r["model_tier"]
        for r in rows
        if r["status"] in ("succeeded", "escalated", "queued", "failed") and r["model_tier"] in TIER_ORDER
    ]
    if not used:
        return None
    return max(used, key=TIER_ORDER.index)


def _enqueue_escalation(
    conn: sqlite3.Connection, claim: sqlite3.Row, reason: str, router: ModelRouter, now_iso: str
) -> bool:
    """Queue a re-extraction one tier up; the runner picks 'queued' rows first (daily cap applies there)."""
    current = _story_tier(conn, claim["story_id"])
    if current is None:
        return False
    nxt = router.escalate(current)
    if nxt is None:
        return False
    exists = conn.execute(
        "SELECT status FROM extraction WHERE story_id = ? AND model_tier = ?", (claim["story_id"], nxt)
    ).fetchone()
    if exists is not None:
        return False  # already attempted or queued at that tier
    pv = conn.execute(
        "SELECT prompt_version FROM extraction WHERE story_id = ? ORDER BY updated_at DESC LIMIT 1",
        (claim["story_id"],),
    ).fetchone()
    conn.execute(
        """INSERT OR IGNORE INTO extraction(story_id, prompt_version, model_tier, custom_id, status, stratum, escalation_reason, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)""",
        (
            claim["story_id"],
            pv["prompt_version"] if pv else "0",
            nxt,
            f"esc_{claim['story_id']}_{nxt}",
            claim["stratum"],
            reason,
            now_iso,
            now_iso,
        ),
    )
    return True


def _enqueue_flag(
    conn: sqlite3.Connection, claim: sqlite3.Row, kind: str, reason: str, payload: object, now_iso: str
) -> bool:
    if conn.execute(
        "SELECT 1 FROM review_queue WHERE claim_id = ? AND kind = ? AND decided_at IS NULL",
        (claim["id"], kind),
    ).fetchone():
        return False
    conn.execute(
        "INSERT INTO review_queue(kind, claim_id, story_id, reason, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            kind,
            claim["id"],
            claim["story_id"],
            reason[:200],
            json.dumps(payload, ensure_ascii=False),
            now_iso,
        ),
    )
    return True


def run_verify(
    conn: sqlite3.Connection,
    *,
    since_hours: int = 72,
    story_ids: list[str] | None = None,
    relabel: bool = False,
    now: datetime | None = None,
    cfg: VerifyConfig | None = None,
    day: str | None = None,
    write_md: bool = True,
) -> VerifyReport:
    t0 = time.monotonic()
    cfg = cfg or load_verify()
    tol = tolerances()
    now = now or datetime.now(UTC)
    now_iso = now.isoformat(timespec="seconds")
    report = VerifyReport()
    router = ModelRouter(load_models())
    key_names = key_person_names()
    for claim in _claims_to_verify(
        conn, since_hours=since_hours, story_ids=story_ids, relabel=relabel, now=now
    ):
        report.considered += 1
        article = _article_for(conn, claim)
        tier = (
            int(article["source_tier"]) if article is not None and article["source_tier"] is not None else 1
        )
        verdict = verify_claim(
            conn,
            claim,
            n_independent=int(claim["story_n_independent"] or 1),
            article=article,
            source_tier=tier,
            now=now,
            cfg=cfg,
            tol=tol,
        )
        conn.execute(
            "UPDATE claim SET confidence = ?, label = ?, signals_json = ? WHERE id = ?",
            (
                verdict.confidence,
                verdict.label.value,
                _merge_signals(claim["signals_json"], verdict),
                claim["id"],
            ),
        )
        report.updated += 1
        report.labels[verdict.label.value] += 1
        impact = float(claim["impact"] if claim["impact"] is not None else (claim["story_impact"] or 0.5))
        if needs_review(impact, verdict.confidence, cfg) and _enqueue_review(conn, claim, verdict, now_iso):
            report.review_added += 1
        reason = escalation_reason(claim, verdict, impact, key_names)
        if reason and _enqueue_escalation(conn, claim, reason, router, now_iso):
            report.escalations_queued += 1
        cands = (verdict.v2.get("correction") or {}).get("candidates") or []
        if cands and _enqueue_flag(conn, claim, "debunk_candidate", cands[0]["title"], cands, now_iso):
            report.debunk_candidates += 1
    conn.commit()
    report.review_open = int(
        conn.execute("SELECT COUNT(*) FROM review_queue WHERE decided_at IS NULL").fetchone()[0]
    )
    if write_md and report.review_open:
        report.review_md = write_review_md(conn, day or now.astimezone(KST).date().isoformat())
    report.elapsed_s = time.monotonic() - t0
    return report


def write_review_md(conn: sqlite3.Connection, day: str) -> Path:
    """review/<day>.md from review/_template.md — every *open* queue item, highest impact first."""
    rows = conn.execute(
        """SELECT q.claim_id, q.reason, c.impact, c.confidence, c.label, c.text, c.signals_json
           FROM review_queue q JOIN claim c ON c.id = q.claim_id
           WHERE q.decided_at IS NULL ORDER BY c.impact DESC, c.confidence ASC, q.id"""
    ).fetchall()
    lines = []
    for i, r in enumerate(rows, 1):
        sig = json.loads(r["signals_json"] or "{}")
        source = sig.get("source_id") or "-"
        text = (r["text"] or "").replace("|", "／").replace("\n", " ")
        text = text if len(text) <= 90 else text[:87] + "…"
        lines.append(
            f"| {i} | `{r['claim_id']}` | {float(r['impact'] or 0):.2f} | {float(r['confidence'] or 0):.2f} | "
            f"{r['label']} | {r['reason']} — {text} | {source} |  |"
        )
    template = (
        TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.exists() else "# 검토 큐 {{date}}\n\n{{rows}}\n"
    )
    out_dir = review_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.md"
    path.write_text(
        template.replace("{{date}}", day).replace(
            "{{rows}}", "\n".join(lines) or "| - | (비어 있음) |  |  |  |  |  |  |"
        ),
        encoding="utf-8",
    )
    return path
