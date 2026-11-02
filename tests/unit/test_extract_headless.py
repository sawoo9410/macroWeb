import json

from macroweb.extract.contracts import StoryInput
from macroweb.extract.headless import build_extract_cmd, parse_claude_json
from macroweb.llm.prompting import load_prompt

STORY = StoryInput(
    story_id="st-0123456789abcdef",
    source_id="yna_economy",
    tier=1,
    stratum="S-T1-KO",
    title="연준 금리 동결",
    text="연준이 기준금리를 동결했다.",
    url="https://www.yna.co.kr/view/x",
    published_at="2026-10-29",
    lang="ko",
)


def test_build_extract_cmd_follows_adr_0007() -> None:
    argv, user = build_extract_cmd(STORY, load_prompt("extract", 1), "small")
    assert argv[:3] == ["claude", "-p", user]
    flags = {argv[i]: argv[i + 1] for i in range(3, len(argv) - 1, 2) if argv[i].startswith("--")}
    assert flags["--model"] == "haiku" and flags["--max-turns"] == "1" and flags["--tools"] == ""
    assert flags["--setting-sources"] == "user" and flags["--output-format"] == "json"
    assert flags["--system-prompt-file"].endswith("prompts/extract/v1.md")
    schema = json.loads(flags["--json-schema"])
    assert schema["additionalProperties"] is False and "claims" in schema["properties"]
    assert "--no-session-persistence" in argv and "--bare" not in argv
    assert "source_id: yna_economy" in user and "stratum: S-T1-KO" in user


def test_parse_claude_json_success_and_limit() -> None:
    ok = parse_claude_json(
        json.dumps(
            {
                "type": "result",
                "is_error": False,
                "result": '{"ok": true}',
                "structured_output": {"ok": True},
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 9,
                    "cache_read_input_tokens": 10701,
                    "cache_creation_input_tokens": 4087,
                },
                "modelUsage": {"claude-haiku-5-5": {}},
                "total_cost_usd": 0.002,
                "duration_ms": 1098,
                "session_id": "s1",
            }
        )
    )
    assert ok.ok and ok.structured == {"ok": True} and ok.usage["cache_read_input_tokens"] == 10701
    assert not ok.limit_hit and ok.error is None and ok.cost_estimate_usd == 0.002
    limited = parse_claude_json(
        json.dumps(
            {"type": "result", "is_error": True, "result": "You've hit your usage limit. Try again at 3pm."}
        ),
        returncode=1,
    )
    assert limited.is_error and limited.limit_hit and not limited.ok
    garbage = parse_claude_json("not json", stderr="rate limit exceeded (429)", returncode=1)
    assert garbage.is_error and garbage.limit_hit and garbage.structured is None
    plain = parse_claude_json(json.dumps({"type": "result", "is_error": False, "result": '{"ok": false}'}))
    assert plain.ok and plain.structured == {"ok": False}
