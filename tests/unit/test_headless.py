from macroweb.synth.headless import build_claude_headless_cmd, headless_env


def test_headless_cmd_has_guards_and_no_bare() -> None:
    cmd = build_claude_headless_cmd("2026-W44")
    assert cmd[:3] == ["claude", "-p", "/weekly-report 2026-W44"]
    for flag in (
        "--output-format",
        "--permission-prompts",
        "--max-turns",
        "--max-budget-usd",
        "--allowedTools",
    ):
        assert flag in cmd
    assert "--bare" not in cmd
    assert cmd[cmd.index("--permission-prompts") + 1] == "none"


def test_headless_env_scrubs_api_key_in_subscription_mode() -> None:
    base = {"ANTHROPIC_API_KEY": "x", "ANTHROPIC_AUTH_TOKEN": "y", "HOME": "/tmp"}
    env = headless_env(base, mode="subscription")
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["HOME"] == "/tmp"
    keep = headless_env(base, mode="api")
    assert keep["ANTHROPIC_API_KEY"] == "x"
