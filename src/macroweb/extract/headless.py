"""Track A on the subscription (ADR-0007): how one Story becomes a `claude -p` call and how its JSON result is
read back. Pure functions — the Phase 2 Extractor runs them with subprocess, records usage, and honours the
per-tick / per-day caps in config/extract.yaml. Mirrors `macroweb.synth.headless` for the weekly job."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from macroweb.config import ExtractConfig, ModelsConfig, TierName, load_extract, load_models
from macroweb.extract.contracts import StoryInput
from macroweb.llm.prompting import PromptSpec, build_extraction_messages
from macroweb.llm.schemas import ExtractionResult, strict_json_schema
from macroweb.paths import PROMPTS_DIR

LIMIT_PATTERNS = re.compile(
    r"(usage limit|rate.?limit|too many requests|\b429\b|quota|limit reached|out of extra usage)",
    re.IGNORECASE,
)


def build_extract_cmd(
    story: StoryInput,
    spec: PromptSpec,
    tier: TierName,
    *,
    extract_cfg: ExtractConfig | None = None,
    models_cfg: ModelsConfig | None = None,
) -> tuple[list[str], str]:
    """Returns (argv, user_prompt). The prompt goes on stdin-free argv as `-p <text>`; the system prompt comes
    from the versioned prompt file so every call is byte-identical except for the story (prompt-cache hit)."""
    ecfg = extract_cfg or load_extract()
    mcfg = models_cfg or load_models()
    model_flag = ecfg.headless.model_flag_by_tier.get(tier) or mcfg.tiers[tier].alias
    _system, user = build_extraction_messages(story, spec, ecfg.max_input_tokens)
    prompt_file = PROMPTS_DIR / spec.name / f"v{spec.version}.md"
    argv = [
        "claude",
        "-p",
        user,
        "--model",
        model_flag,
        "--system-prompt-file",
        str(prompt_file),
        "--setting-sources",
        ecfg.headless.setting_sources,
        "--tools",
        "",
        "--max-turns",
        str(ecfg.headless.max_turns),
        "--json-schema",
        json.dumps(strict_json_schema(ExtractionResult), ensure_ascii=False, separators=(",", ":")),
        "--output-format",
        "json",
        "--no-session-persistence",
    ]
    return argv, user


@dataclass
class HeadlessResult:
    ok: bool
    structured: dict[str, Any] | None
    text: str | None
    usage: dict[str, int]
    model_usage: dict[str, Any]
    cost_estimate_usd: float
    is_error: bool
    limit_hit: bool
    error: str | None
    duration_ms: int | None
    session_id: str | None
    subtype: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    stderr: str = ""


def parse_claude_json(stdout: str, stderr: str = "", returncode: int = 0) -> HeadlessResult:
    """Read `claude -p --output-format json` output. `structured_output` holds the schema-validated object when
    `--json-schema` was used; otherwise `result` is text. Subscription-limit errors set `limit_hit`."""
    try:
        d = json.loads(stdout) if stdout.strip().startswith("{") else {}
    except json.JSONDecodeError:
        d = {}
    usage_raw = d.get("usage") or {}
    usage = {
        "input_tokens": int(usage_raw.get("input_tokens") or 0),
        "output_tokens": int(usage_raw.get("output_tokens") or 0),
        "cache_read_input_tokens": int(usage_raw.get("cache_read_input_tokens") or 0),
        "cache_creation_input_tokens": int(usage_raw.get("cache_creation_input_tokens") or 0),
    }
    is_error = bool(d.get("is_error")) or returncode != 0 or not d
    text = d.get("result") if isinstance(d.get("result"), str) else None
    structured = d.get("structured_output") if isinstance(d.get("structured_output"), dict) else None
    if structured is None and text and text.strip().startswith("{"):
        try:
            structured = json.loads(text)
        except json.JSONDecodeError:
            structured = None
    subtype = d.get("subtype") if isinstance(d.get("subtype"), str) else None
    pieces: list[str] = []
    if is_error:
        if subtype and subtype != "success":
            pieces.append(subtype)
        if text:
            pieces.append(text)
        if d.get("error"):
            pieces.append(str(d["error"]))
        if not d and stdout.strip():
            pieces.append(stdout.strip()[:200])
    if stderr.strip():
        pieces.append(stderr.strip())
    err_text = " ".join(pieces)
    limit_hit = bool(LIMIT_PATTERNS.search(err_text)) if (is_error or stderr) else False
    return HeadlessResult(
        ok=not is_error and structured is not None,
        structured=structured,
        text=text,
        usage=usage,
        model_usage=d.get("modelUsage") or {},
        cost_estimate_usd=float(d.get("total_cost_usd") or 0.0),
        is_error=is_error,
        limit_hit=limit_hit,
        error=(err_text.strip()[:300] or None) if is_error else None,
        duration_ms=d.get("duration_ms"),
        session_id=d.get("session_id"),
        subtype=subtype,
        raw=d,
        stderr=stderr[-4000:],
    )
