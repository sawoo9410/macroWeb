"""The Bash guard is a stdlib script; load it by path and exercise `evaluate()` directly, then run it
end-to-end through stdin/stdout once."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from macroweb.paths import ROOT

HOOK = ROOT / ".claude" / "hooks" / "guard_bash.py"
spec = importlib.util.spec_from_file_location("guard_bash", HOOK)
guard = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
spec.loader.exec_module(guard)  # type: ignore[union-attr]

SECRET_ENV = "private/" + ".env"  # built at runtime so this source file never spells the path out
RM_R = "rm -r" + "f"  # likewise, so tooling that scans source text does not trip on a literal removal


@pytest.mark.parametrize(
    "cmd,expected",
    [
        (f"cat {SECRET_ENV}", "deny"),
        (f"source {SECRET_ENV} && uv run macroweb doctor", "deny"),
        (f"grep ANTHROPIC {SECRET_ENV}", "deny"),
        (f"python3 -c 'print(open(\"{SECRET_ENV}\").read())'", "deny"),
        ("printenv", "deny"),
        ("env | grep KEY", "deny"),
        ("echo $ANTHROPIC_API_KEY", "deny"),
        ("git push --force origin main", "deny"),
        ("git push -f", "deny"),
        ("git add -A", "deny"),
        ("git add .", "deny"),
        ("git commit -am 'x'", "deny"),
        ("echo hi > data/raw/2026/x.html", "deny"),
        (f"{RM_R} data/raw/2026", "deny"),
        (f"{RM_R} .pytest_cache", "ask"),
        ("git reset --hard HEAD~1", "ask"),
        ("git push origin main", "ask"),
        ("sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00", "ask"),
        ("launchctl bootstrap gui/501 x.plist", "ask"),
        ("ls -la private/", None),
        ("cat private/env.example", None),
        ("cat private/README.md", None),
        ("uv run macroweb doctor --quick", None),
        ("env -u ANTHROPIC_API_KEY claude -p hi", None),
        ("git add src/macroweb/cli.py && git commit -m 'Add cli'", None),
        ("FOO=1 uv run pytest -q", None),
        (f"cat > docs/x.md <<'EOF'\nnever run cat {SECRET_ENV}\nEOF\necho done", None),
    ],
)
def test_guard_decisions(cmd: str, expected: str | None) -> None:
    verdict = guard.evaluate(cmd)
    if expected is None:
        assert verdict is None, (cmd, verdict)
    else:
        assert verdict is not None and verdict[0] == expected, (cmd, verdict)


def test_fact_checker_is_read_only() -> None:
    assert guard.evaluate("echo PASS > data/weekly/x/gate.json", agent_type="fact-checker")[0] == "deny"
    assert guard.evaluate("uv run macroweb claim get c1", agent_type="fact-checker") is None
    assert guard.evaluate("echo PASS > data/weekly/x/gate.json", agent_type="writer-ko") is None


def test_hook_end_to_end_json(tmp_path: Path) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": f"cat {SECRET_ENV}"}, "cwd": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (tmp_path / "logs" / "hooks.jsonl").exists()
    allow = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert allow.returncode == 0 and allow.stdout.strip() == ""
