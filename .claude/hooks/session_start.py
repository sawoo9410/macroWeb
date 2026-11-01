#!/usr/bin/env python3
"""SessionStart hook (PLAN §13.4). Plain stdout from a SessionStart hook is added to Claude's context
(code.claude.com/docs/en/hooks, verified 2026-11-01). Stdlib only; runs on the system python3 (3.9+)."""

import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    lines = ["MacroWeb (거미줄) session context — produced by .claude/hooks/session_start.py:"]

    status_path = root / "docs" / "phase_status.json"
    if status_path.exists():
        try:
            st = json.loads(status_path.read_text(encoding="utf-8"))
            ph = str(st.get("current_phase"))
            info = st["phases"][ph]
            dod = info["dod"]
            done = [i["id"] for i in dod if i.get("done")]
            todo = [i["id"] for i in dod if not i.get("done")]
            lines.append(
                "- Current Phase %s (%s): %d/%d DoD done. Next TODO: %s"
                % (
                    ph,
                    info["name"],
                    len(done),
                    len(dod),
                    ", ".join(todo[:6])
                    if todo
                    else "none — phase complete, run `uv run macroweb phase advance`",
                )
            )
        except Exception as exc:  # keep the session usable even if the file is malformed
            lines.append("- phase_status.json unreadable: %s" % type(exc).__name__)
    lines.append(
        "- Read docs/PLAN_DIGEST.md first. PLAN.md is the SSOT; ADRs in docs/decisions/ win on conflict."
    )

    q = root / "docs" / "QUESTIONS.md"
    if q.exists():
        open_q = sum(1 for line in q.read_text(encoding="utf-8").splitlines() if line.startswith("- [ ]"))
        lines.append(
            "- Open 🔒 questions: %d (docs/QUESTIONS.md). Do not block on them; use PLAN §0.3 defaults."
            % open_q
        )

    adr_dir = root / "docs" / "decisions"
    if adr_dir.exists():
        adrs = sorted(p.stem for p in adr_dir.glob("*.md"))
        if adrs:
            lines.append("- ADRs: " + ", ".join(adrs[-6:]))

    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "--branch"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            out = r.stdout.splitlines()
            lines.append("- git: %s, %d uncommitted paths" % (out[0] if out else "?", max(0, len(out) - 1)))
    except Exception:
        pass

    lines.append(
        "- Hard rules: never read/print private/ or .env* (variable names: private/env.example); "
        "git add only your own files (no -A/-a), no force push; keep Phase order; `make doctor` must pass before a Phase ends."
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
