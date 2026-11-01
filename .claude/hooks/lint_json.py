#!/usr/bin/env python3
"""PostToolUse(Edit|Write) lint (PLAN §13.4): JSON must parse; config/ and prompts/ files must pass
`macroweb config validate`; agent and skill frontmatter must have the required fields. On failure exit 2 so
Claude sees the message (tool already ran). Stdlib only; runs on system python3 (3.9+)."""

import json
import os
import re
import subprocess
import sys


def fail(msg):
    sys.stderr.write("lint_json.py: " + msg + "\n")
    sys.exit(2)


def frontmatter(text):
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    fp = (payload.get("tool_input") or {}).get("file_path")
    if not fp or not os.path.exists(fp):
        sys.exit(0)
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    rel = os.path.relpath(fp, root).replace("\\", "/")

    if fp.endswith(".json"):
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                json.load(fh)
        except Exception as exc:
            fail("%s is not valid JSON: %s" % (rel, exc))

    if rel.startswith("config/") or rel.startswith("prompts/"):
        try:
            r = subprocess.run(
                ["uv", "run", "-q", "macroweb", "config", "validate", "--path", fp],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=55,
            )
        except FileNotFoundError:
            sys.exit(0)  # uv missing: doctor reports it
        except subprocess.TimeoutExpired:
            fail("config validate timed out for %s" % rel)
        if r.returncode != 0:
            tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])
            fail("schema validation failed for %s:\n%s" % (rel, tail))

    if re.match(r"^\.claude/agents/[^/]+\.md$", rel):
        with open(fp, "r", encoding="utf-8") as fh:
            fm = frontmatter(fh.read())
        if fm is None or "name:" not in fm or "description:" not in fm:
            fail(
                "%s: subagent frontmatter needs `name:` and `description:` as the first block (docs: sub-agents)"
                % rel
            )
    if re.match(r"^\.claude/skills/[^/]+/SKILL\.md$", rel):
        with open(fp, "r", encoding="utf-8") as fh:
            fm = frontmatter(fh.read())
        if fm is None or "description:" not in fm:
            fail("%s: SKILL.md frontmatter needs `description:`" % rel)
    sys.exit(0)


if __name__ == "__main__":
    main()
