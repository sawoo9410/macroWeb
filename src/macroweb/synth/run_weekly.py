"""Weekly editorial runner (Phase 4 v1, ADR-0002/0010): quality review → data pack → `claude -p /weekly-report`
(the skill drives the agents) → deterministic gate on the draft → publish. `--dry-run` does everything except the
model call and gates whatever draft exists. Partial outputs are never deleted; every step is appended to
data/weekly/<week>/steps.jsonl so a rerun can be inspected."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from macroweb.db import repo
from macroweb.graph.analysis import iso_week
from macroweb.paths import ROOT
from macroweb.publish.weekly import PublishResult, publish_report
from macroweb.quality.weekly import run_quality
from macroweb.synth.gate import GateResult, check_draft
from macroweb.synth.headless import build_claude_headless_cmd, headless_env
from macroweb.synth.pack import weekly_dir, write_pack

DRAFT_CANDIDATES = ("draft_final.md", "draft.md")


def record_step(week: str, step: str, status: str, **extra: Any) -> Path:
    d = weekly_dir(week)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "steps.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                    "step": step,
                    "status": status,
                    **extra,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return p


def find_draft(week: str) -> Path | None:
    d = weekly_dir(week)
    for name in DRAFT_CANDIDATES:
        p = d / name
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


@dataclass
class WeeklyRunReport:
    week: str
    quality_line: str | None = None
    pack_path: Path | None = None
    claude_rc: int | None = None
    claude_subtype: str | None = None
    claude_usage: dict[str, Any] = field(default_factory=dict)
    cost_estimate_usd: float = 0.0
    draft: Path | None = None
    gate: GateResult | None = None
    published: PublishResult | None = None
    stopped: str | None = None
    elapsed_s: float = 0.0

    def render(self) -> str:
        lines = [f"weekly {self.week}: {self.quality_line or '-'}", f"pack: {self.pack_path}"]
        if self.claude_rc is not None:
            lines.append(
                f"claude -p rc={self.claude_rc} subtype={self.claude_subtype} cost_est=${self.cost_estimate_usd:.2f} usage={self.claude_usage}"
            )
        lines.append(f"draft: {self.draft or 'none'}")
        if self.gate:
            lines.append(self.gate.render())
        if self.published:
            lines.append(f"published: {self.published.report}")
        if self.stopped:
            lines.append(f"stopped: {self.stopped}")
        lines.append(f"{self.elapsed_s:.0f}s")
        return "\n".join(lines)


def run_claude(week: str, *, timeout_s: int) -> tuple[int, dict[str, Any], str]:
    """One `claude -p "/weekly-report <week>"` in the repo (project settings load the skills/agents)."""
    cmd = build_claude_headless_cmd(week)
    env = headless_env()
    env.setdefault("HOME", os.path.expanduser("~"))
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, cwd=ROOT, env=env)
    except subprocess.TimeoutExpired:
        return 124, {}, f"timeout after {timeout_s}s"
    try:
        data = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    return p.returncode, data, p.stderr[-2000:]


def run_weekly(
    week: str | None = None,
    *,
    dry_run: bool = False,
    timeout_s: int = 7200,
    skip_quality: bool = False,
    conn: sqlite3.Connection | None = None,
    publish_dirs: dict[str, Path] | None = None,
    notify: bool = True,
) -> WeeklyRunReport:
    t0 = time.monotonic()
    week = week or iso_week()
    rep = WeeklyRunReport(week=week)
    own = conn is None
    if own:
        repo.init_db()
        conn = repo.connect()
    assert conn is not None
    run_id = repo.start_run(conn, "weekly")
    try:
        if not skip_quality:
            q = run_quality(conn, week)
            rep.quality_line = q.scoreline()
            record_step(week, "quality", "ok", scoreline=rep.quality_line)
        paths = write_pack(conn, week)
        rep.pack_path = paths.pack
        record_step(week, "pack", "ok", pack=str(paths.pack), slices=sorted(paths.slices))
        if not dry_run:
            if os.environ.get("MACROWEB_DISABLE_LLM"):
                raise RuntimeError("MACROWEB_DISABLE_LLM is set: refusing to call claude -p (use --dry-run)")
            rc, data, err = run_claude(week, timeout_s=timeout_s)
            rep.claude_rc, rep.claude_subtype = rc, data.get("subtype")
            rep.claude_usage = {
                k: data.get("usage", {}).get(k)
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                )
            }
            rep.cost_estimate_usd = float(data.get("total_cost_usd") or 0.0)
            record_step(
                week,
                "claude",
                "ok" if rc == 0 and not data.get("is_error") else "failed",
                rc=rc,
                subtype=rep.claude_subtype,
                stderr=err[-500:],
            )
            if rc != 0 or data.get("is_error"):
                rep.stopped = f"claude -p failed (rc={rc}, {rep.claude_subtype or err[-200:]})"
        rep.draft = find_draft(week)
        if rep.draft is None:
            rep.stopped = (
                rep.stopped or f"no draft in {weekly_dir(week)} (expected one of {DRAFT_CANDIDATES})"
            )
            return rep
        errata = bool(
            conn.execute(
                "SELECT q5_errata FROM quality_run WHERE week = ? AND COALESCE(q5_errata, 0) > 0", (week,)
            ).fetchone()
        )
        rep.gate = check_draft(conn, rep.draft.read_text(encoding="utf-8"), errata_required=errata)
        (weekly_dir(week) / "gate.json").write_text(
            json.dumps(rep.gate.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        record_step(week, "gate", "ok" if rep.gate.passed else "failed", violations=len(rep.gate.violations))
        if not rep.gate.passed:
            rep.stopped = rep.stopped or "gate FAIL — draft kept, nothing published"
            return rep
        rep.published = publish_report(conn, week, rep.draft, notify=notify, **(publish_dirs or {}))
        record_step(week, "publish", "ok", report=str(rep.published.report))
        return rep
    finally:
        rep.elapsed_s = time.monotonic() - t0
        repo.finish_run(
            conn,
            run_id,
            "ok" if rep.published else ("dry-run" if dry_run and not rep.stopped else "failed"),
            {
                "week": week,
                "quality": rep.quality_line,
                "pack": str(rep.pack_path) if rep.pack_path else None,
                "claude_rc": rep.claude_rc,
                "gate": rep.gate.as_dict() if rep.gate else None,
                "published": str(rep.published.report) if rep.published else None,
                "stopped": rep.stopped,
                "elapsed_s": round(rep.elapsed_s, 1),
            },
            tokens_in=int(
                (rep.claude_usage.get("input_tokens") or 0)
                + (rep.claude_usage.get("cache_read_input_tokens") or 0)
                + (rep.claude_usage.get("cache_creation_input_tokens") or 0)
            ),
            tokens_out=int(rep.claude_usage.get("output_tokens") or 0),
            model_tier="mixed",
            cost_usd=0.0,
        )
        if own:
            conn.close()
