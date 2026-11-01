#!/usr/bin/env python3
"""Stop hook (PLAN §13.4): summarize the current Phase DoD and a quick `macroweb doctor` as a
`systemMessage` (shown to the user; Stop stdout itself only goes to the debug log — verified against
code.claude.com/docs/en/hooks on 2026-11-01). Never blocks: no exit 2, no decision=block."""

import json
import os
import subprocess
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    parts = []

    status_path = os.path.join(root, "docs", "phase_status.json")
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as fh:
                st = json.load(fh)
            ph = str(st.get("current_phase"))
            dod = st["phases"][ph]["dod"]
            todo = [i["id"] for i in dod if not i.get("done")]
            parts.append("Phase %s DoD %d/%d" % (ph, len(dod) - len(todo), len(dod)))
            if todo:
                parts.append("next: " + ", ".join(todo[:3]))
        except Exception as exc:
            parts.append("phase_status unreadable (%s)" % type(exc).__name__)

    try:
        r = subprocess.run(
            ["uv", "run", "-q", "macroweb", "doctor", "--quick", "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=50,
        )
        data = json.loads(r.stdout) if r.stdout.strip().startswith("{") else None
        if data:
            counts = {}
            for c in data.get("checks", []):
                counts[c["status"]] = counts.get(c["status"], 0) + 1
            fails = [c["name"] for c in data.get("checks", []) if c["status"] == "FAIL"]
            parts.append(
                "doctor: %s" % " ".join("%s %d" % (k, counts.get(k, 0)) for k in ("PASS", "WARN", "FAIL"))
            )
            if fails:
                parts.append("FAIL: " + ", ".join(fails[:5]))
        else:
            parts.append("doctor: no JSON (rc=%s)" % r.returncode)
    except FileNotFoundError:
        parts.append("doctor: uv not found")
    except subprocess.TimeoutExpired:
        parts.append("doctor: timeout")
    except Exception as exc:
        parts.append("doctor: %s" % type(exc).__name__)

    msg = "MacroWeb · " + " · ".join(parts)
    print(json.dumps({"systemMessage": msg[:900]}, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
