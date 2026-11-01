"""`macroweb doctor` — environment, DB integrity, config schemas, hooks, keys (presence only), disk,
launchd, cost cap and (full mode) source probes (PLAN §13.6). Exit 1 only on FAIL; WARN is informational."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Literal

from macroweb import paths
from macroweb.config import load_models, validate_all
from macroweb.db import repo

Status = Literal["PASS", "WARN", "FAIL", "INFO"]
REQUIRED_PATHS = [
    "PLAN.md",
    "CLAUDE.md",
    "Makefile",
    "pyproject.toml",
    "docs/PLAN_DIGEST.md",
    "docs/QUESTIONS.md",
    "docs/phase_status.json",
    "docs/decisions",
    ".claude/settings.json",
    ".claude/agents",
    ".claude/skills",
    ".claude/hooks/session_start.py",
    ".claude/hooks/guard_bash.py",
    ".claude/hooks/lint_json.py",
    ".claude/hooks/phase_check.py",
    "config/sources.yaml",
    "config/models.yaml",
    "src/macroweb/db/schema.sql",
    "launchd",
    "bin/run_collect.sh",
    "bin/run_daily.sh",
    "bin/run_weekly.sh",
    "bin/run_monthly.sh",
    "reports/_template.md",
    "seed",
    "prompts/extract/v1.md",
]
KEY_VARS = ["ANTHROPIC_API_KEY", "FRED_API_KEY", "ECOS_API_KEY", "DART_API_KEY", "TELEGRAM_BOT_TOKEN"]
LAUNCHD_LABELS = [
    "com.sawoo.macroweb.collect",
    "com.sawoo.macroweb.daily",
    "com.sawoo.macroweb.weekly",
    "com.sawoo.macroweb.monthly",
]


@dataclass
class Check:
    name: str
    status: Status
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 12)
    return Check("python", "PASS" if ok else "FAIL", f"{platform.python_version()} ({sys.executable})")


def _tools() -> list[Check]:
    out: list[Check] = []
    for tool, sev in (
        ("uv", "FAIL"),
        ("claude", "WARN"),
        ("git", "WARN"),
        ("caffeinate", "WARN"),
        ("launchctl", "WARN"),
    ):
        path = shutil.which(tool)
        out.append(Check(f"tool:{tool}", "PASS" if path else sev, path or "not found on PATH"))  # type: ignore[arg-type]
    return out


def _imports() -> Check:
    missing = []
    for mod in ("anthropic", "pydantic", "typer", "yaml", "httpx", "rich"):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001
            missing.append(mod)
    return Check(
        "deps",
        "FAIL" if missing else "PASS",
        f"missing: {missing}" if missing else "anthropic/pydantic/typer/yaml/httpx/rich",
    )


def _playwright() -> Check:
    try:
        __import__("playwright")
        return Check("playwright", "PASS", "python package installed (browser install checked in Phase 1)")
    except Exception:  # noqa: BLE001
        return Check(
            "playwright",
            "WARN",
            "not installed — needed from Phase 1 for CME FedWatch (uv add playwright && uv run playwright install chromium)",
        )


def _structure() -> Check:
    missing = [p for p in REQUIRED_PATHS if not (paths.ROOT / p).exists()]
    return Check(
        "repo-structure",
        "FAIL" if missing else "PASS",
        f"missing: {missing}" if missing else f"{len(REQUIRED_PATHS)} required paths present",
    )


def _config() -> Check:
    results = validate_all()
    bad = [r for r in results if not r.ok]
    if bad:
        return Check("config", "FAIL", "; ".join(f"{r.name}: {r.message}" for r in bad)[:400])
    return Check("config", "PASS", f"{len(results)} files valid")


def _settings_and_hooks() -> list[Check]:
    out: list[Check] = []
    sp = paths.CLAUDE_DIR / "settings.json"
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        hooks = data.get("hooks", {})
        need = {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}
        missing = need - set(hooks)
        out.append(
            Check(
                "claude-settings",
                "FAIL" if missing else "PASS",
                f"hooks missing {sorted(missing)}" if missing else f"hooks: {sorted(hooks)}",
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        out.append(Check("claude-settings", "FAIL", f"{type(exc).__name__}: {exc}"))
    for h in ("session_start.py", "guard_bash.py", "lint_json.py", "phase_check.py"):
        p = paths.CLAUDE_DIR / "hooks" / h
        if not p.exists():
            out.append(Check(f"hook:{h}", "FAIL", "missing"))
            continue
        r = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True, text=True)
        out.append(
            Check(
                f"hook:{h}",
                "PASS" if r.returncode == 0 else "FAIL",
                "compiles" if r.returncode == 0 else r.stderr.strip()[:200],
            )
        )
    agents = sorted(p.stem for p in (paths.CLAUDE_DIR / "agents").glob("*.md"))
    skills = sorted(p.parent.name for p in (paths.CLAUDE_DIR / "skills").glob("*/SKILL.md"))
    out.append(Check("agents", "PASS" if len(agents) >= 14 else "WARN", f"{len(agents)} agents"))
    out.append(Check("skills", "PASS" if len(skills) >= 9 else "WARN", f"{len(skills)} skills"))
    return out


def _db() -> list[Check]:
    out: list[Check] = []
    p = paths.db_path()
    if not p.exists():
        return [Check("db", "WARN", f"{p} missing — run `make db-init`")]
    try:
        conn = repo.connect(p)
        try:
            ic = repo.integrity_check(conn)
            ver = repo.schema_version(conn)
            tables = repo.table_names(conn)
            out.append(Check("db-integrity", "PASS" if ic == "ok" else "FAIL", f"integrity_check={ic}"))
            out.append(
                Check(
                    "db-schema",
                    "PASS" if ver >= repo.SCHEMA_VERSION else "FAIL",
                    f"schema_version={ver}, tables={len(tables)}",
                )
            )
            out.append(
                Check(
                    "db-fts5",
                    "PASS" if repo.fts5_available(conn) else "FAIL",
                    "FTS5 available" if repo.fts5_available(conn) else "no FTS5",
                )
            )
            tri = repo.trigram_available(conn)
            out.append(
                Check(
                    "db-trigram",
                    "PASS" if tri else "WARN",
                    f"sqlite {sqlite3.sqlite_version}: trigram {'ok' if tri else 'unavailable (unicode61 fallback)'}",
                )
            )
            out.append(Check("db-wal", "PASS", str(conn.execute("PRAGMA journal_mode").fetchone()[0])))
        finally:
            conn.close()
    except sqlite3.Error as exc:
        out.append(Check("db", "FAIL", f"{type(exc).__name__}: {exc}"))
    return out


def _keys() -> list[Check]:
    out: list[Check] = []
    env_file = paths.PRIVATE_DIR / ".env"
    out.append(
        Check(
            "private/.env",
            "PASS" if env_file.exists() else "WARN",
            "exists (not read)"
            if env_file.exists()
            else "missing — cp private/env.example private/.env (needed from Phase 1/2)",
        )
    )
    for var in KEY_VARS:
        present = bool(os.environ.get(var))
        out.append(
            Check(
                f"env:{var}",
                "PASS" if present else "WARN",
                "set" if present else "not set in this process (bin/ wrappers source private/.env)",
            )
        )
    return out


def _disk() -> Check:
    usage = shutil.disk_usage(paths.ROOT)
    free_gb = usage.free / 1e9
    status: Status = "PASS" if free_gb >= 10 else ("WARN" if free_gb >= 2 else "FAIL")
    return Check("disk", status, f"{free_gb:.0f} GB free")


def _launchd(phase: str) -> list[Check]:
    out: list[Check] = []
    if not shutil.which("launchctl"):
        return [Check("launchd", "WARN", "launchctl not found")]
    uid = os.getuid()
    loaded = []
    for label in LAUNCHD_LABELS:
        r = subprocess.run(["launchctl", "print", f"gui/{uid}/{label}"], capture_output=True, text=True)
        if r.returncode == 0:
            loaded.append(label.rsplit(".", 1)[-1])
    if loaded:
        out.append(Check("launchd", "PASS", f"loaded: {loaded}"))
    else:
        sev: Status = "INFO" if phase == "0" else "WARN"
        out.append(
            Check("launchd", sev, "no macroweb jobs loaded (expected before Phase 1; `make launchd-install`)")
        )
    return out


def _cost_cap() -> Check:
    try:
        cfg = load_models()
        p = paths.db_path()
        spent = 0.0
        if p.exists():
            conn = repo.connect(p)
            try:
                spent = repo.month_cost_usd(conn)
            finally:
                conn.close()
        cap = cfg.budget.monthly_cap_usd
        pct = spent / cap * 100 if cap else 0
        status: Status = (
            "PASS" if pct < cfg.budget.soft_limit_pct * 100 else ("WARN" if pct < 100 else "FAIL")
        )
        return Check("cost-cap", status, f"${spent:.2f} / ${cap:.0f} this month ({pct:.0f}%)")
    except Exception as exc:  # noqa: BLE001
        return Check("cost-cap", "WARN", f"{type(exc).__name__}: {exc}")


def _git() -> Check:
    r = subprocess.run(
        ["git", "status", "--porcelain", "--branch"], cwd=paths.ROOT, capture_output=True, text=True
    )
    if r.returncode != 0:
        return Check("git", "WARN", "not a git repository")
    lines = r.stdout.splitlines()
    dirty = len(lines) - 1
    return Check("git", "INFO", f"{lines[0] if lines else ''} dirty={dirty}")


def _sources_probe() -> list[Check]:
    from macroweb.collect.registry import probe_all

    results = probe_all(enabled_only=True)
    bad = [r for r in results if not r.ok]
    out = [
        Check(
            "sources",
            "PASS" if len(bad) <= len(results) * 0.2 else "WARN",
            f"{len(results) - len(bad)}/{len(results)} enabled sources reachable",
        )
    ]
    for r in bad:
        out.append(Check(f"source:{r.id}", "WARN", f"status={r.status} error={r.error}"))
    return out


def run_doctor(quick: bool = True, phase: str | None = None) -> list[Check]:
    if phase is None:
        try:
            from macroweb import phase as phase_mod

            phase = phase_mod.current_phase()
        except Exception:  # noqa: BLE001
            phase = "0"
    checks: list[Check] = [_python(), *_tools(), _imports(), _playwright(), _structure(), _config()]
    checks += _settings_and_hooks()
    checks += _db()
    checks += _keys()
    checks += [_disk(), *_launchd(phase), _cost_cap(), _git()]
    if not quick:
        checks += _sources_probe()
    return checks


def worst(checks: list[Check]) -> Status:
    order = {"FAIL": 3, "WARN": 2, "PASS": 1, "INFO": 0}
    return max(checks, key=lambda c: order[c.status]).status if checks else "PASS"
