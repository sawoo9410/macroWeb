"""Weekly editorial runner = `claude -p` headless (ADR-0002). This module only builds the command and the
environment; the Phase 4 runner (`run_weekly.py`) executes it with a timeout and records the `run` row.

Facts verified against code.claude.com docs on 2026-11-01 (ADR-0001):
- `--permission-prompts none` (v2.1.259+) denies anything that would prompt instead of hanging.
- `--max-turns` / `--max-budget-usd` are print-mode guards; the budget is a client-side estimate.
- `--bare` skips OAuth/keychain, so it must NOT be used on the subscription path.
- Auth precedence puts `ANTHROPIC_API_KEY` above subscription OAuth, so the key is scrubbed from the
  child environment unless mode == "api"."""

from __future__ import annotations

import os
from collections.abc import Mapping

from macroweb.config import load_models

API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def build_claude_headless_cmd(
    week: str,
    *,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    allowed_tools: tuple[str, ...] = (
        "Read",
        "Edit",
        "Write",
        "Bash(uv run macroweb *)",
        "Bash(uv run python *)",
        "Agent",
        "Skill",
    ),
) -> list[str]:
    cfg = load_models().weekly_runner
    cmd = [
        "claude",
        "-p",
        f"/weekly-report {week}",
        "--output-format",
        "json",
        "--permission-mode",
        permission_mode,
        "--permission-prompts",
        "none",
        "--allowedTools",
        ",".join(allowed_tools),
        "--max-turns",
        str(max_turns or cfg.max_turns),
        "--max-budget-usd",
        str(max_budget_usd or cfg.max_budget_usd),
        "--name",
        f"macroweb-weekly-{week}",
    ]
    return cmd


def headless_env(base: Mapping[str, str] | None = None, mode: str | None = None) -> dict[str, str]:
    """Child env for the claude process. Subscription mode removes API credentials so billing stays on the
    subscription; `MACROWEB_WEEKLY_AUTH=api` keeps them (billed to the Console key)."""
    env = dict(base if base is not None else os.environ)
    mode = (
        mode
        or env.get("MACROWEB_WEEKLY_AUTH")
        or ("api" if load_models().weekly_runner.mode == "api" else "subscription")
    )
    if mode != "api":
        for var in API_KEY_VARS:
            env.pop(var, None)
    env["MACROWEB_ENV"] = env.get("MACROWEB_ENV", "prod")
    return env
