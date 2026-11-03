"""Headless extractor (ADR-0007): one `claude -p` per Story, sequential, with per-run and per-day call caps,
subscription-limit backoff, schema retry + one escalation (PLAN §6.2.2 rule 1), and the ledger
(`llm_batch` per run, `extraction` per story×prompt×tier). Everything that touches the model goes through
`run_cmd`, which tests replace with a fake."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from macroweb.config import ExtractConfig, ModelsConfig, TierName, load_extract, load_models
from macroweb.extract.contracts import ExtractionOutcome, ExtractionRequest, StoryInput
from macroweb.extract.headless import HeadlessResult, build_extract_cmd, parse_claude_json
from macroweb.extract.persist import PersistStats, alias_index, persist_result
from macroweb.extract.select import Candidate
from macroweb.llm.prompting import PromptSpec, load_prompt
from macroweb.llm.router import ModelRouter
from macroweb.llm.schemas import ExtractionResult
from macroweb.paths import LOGS_DIR, data_dir
from macroweb.synth.headless import headless_env

KST = ZoneInfo("Asia/Seoul")
RunCmd = Callable[[list[str]], tuple[str, str, int]]
LIMIT_STAMP = LOGS_DIR / "claude_limit.stamp"
LADDER: tuple[TierName, ...] = ("small", "mid", "large")


@dataclass
class RunReport:
    batch_id: str
    selected: int = 0
    calls: int = 0
    succeeded: int = 0
    failed: int = 0
    escalated: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    claims: int = 0
    entities_new: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_estimate_usd: float = 0.0
    limit_hit: bool = False
    stopped_reason: str | None = None
    elapsed_s: float = 0.0

    def render(self) -> str:
        parts = [
            f"extract batch={self.batch_id} selected={self.selected} calls={self.calls} ok={self.succeeded} failed={self.failed} "
            f"escalated={self.escalated} claims={self.claims} entities_new={self.entities_new} "
            f"tokens in/out={self.tokens_in}/{self.tokens_out} cost_est=${self.cost_estimate_usd:.3f} {self.elapsed_s:.1f}s"
        ]
        if self.skipped:
            parts.append(f"skipped: {self.skipped}")
        if self.stopped_reason:
            parts.append(f"stopped: {self.stopped_reason}")
        return "\n".join(parts)


def default_run_cmd(timeout_s: int = 180, work_dir: Path | None = None) -> RunCmd:
    work = work_dir or (data_dir() / "work")
    work.mkdir(parents=True, exist_ok=True)

    def run(argv: list[str]) -> tuple[str, str, int]:
        env = headless_env(mode="subscription")
        env.setdefault("HOME", os.path.expanduser("~"))
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, cwd=work, env=env)
        except subprocess.TimeoutExpired:
            return "", f"timeout after {timeout_s}s", 124
        return p.stdout, p.stderr, p.returncode

    return run


def _default_sentinel(argv: list[str]) -> tuple[str, str, int]:  # replaced lazily by default_run_cmd()
    raise RuntimeError("sentinel run_cmd invoked")


_DEFAULT_SENTINEL: RunCmd = _default_sentinel


def kst_day_start_utc(now: datetime) -> str:
    local = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC).isoformat(timespec="seconds")


class HeadlessExtractor:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        extract_cfg: ExtractConfig | None = None,
        models_cfg: ModelsConfig | None = None,
        run_cmd: RunCmd | None = None,
        now: datetime | None = None,
        limit_stamp: Path | None = None,
    ) -> None:
        self.conn = conn
        self.ecfg = extract_cfg or load_extract()
        self.mcfg = models_cfg or load_models()
        self.router = ModelRouter(self.mcfg)
        self.run_cmd = run_cmd or _DEFAULT_SENTINEL
        self._fixed_clock = now is not None
        self.now = now or datetime.now(UTC)
        self.limit_stamp = limit_stamp or LIMIT_STAMP
        self.prompt: PromptSpec = load_prompt(self.ecfg.prompt.name, self.ecfg.prompt.version)
        self.aliases = alias_index()

    def _clock(self) -> datetime:
        """Injected `now` is honoured everywhere (tests, replays); otherwise the wall clock."""
        return self.now if self._fixed_clock else datetime.now(UTC)

    # --- caps & guards -------------------------------------------------------------------------------
    def calls_today(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(n_requests), 0) AS n FROM llm_batch WHERE submitted_at >= ?",
            (kst_day_start_utc(self.now),),
        ).fetchone()
        return int(row["n"])

    def escalations_today(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM extraction WHERE escalation_reason IS NOT NULL AND created_at >= ?",
            (kst_day_start_utc(self.now),),
        ).fetchone()
        return int(row["n"])

    def limit_backoff_active(self) -> bool:
        if not self.limit_stamp.exists():
            return False
        age = time.time() - self.limit_stamp.stat().st_mtime
        return age < self.ecfg.headless.limit_backoff_s

    def _mark_limit(self) -> None:
        self.limit_stamp.parent.mkdir(parents=True, exist_ok=True)
        self.limit_stamp.write_text(self.now.isoformat(timespec="seconds"), encoding="utf-8")

    # --- ledger ----------------------------------------------------------------------------------------
    def _open_batch(self) -> str:
        bid = f"hb-{self.now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.conn.execute(
            "INSERT INTO llm_batch(id, job, model_tier, prompt_version, submitted_at, status) VALUES (?, 'extract', 'mixed', ?, ?, 'running')",
            (bid, str(self.prompt.version), self.now.isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return bid

    def _close_batch(self, report: RunReport) -> None:
        self.conn.execute(
            """UPDATE llm_batch SET ended_at = ?, status = ?, n_requests = ?, n_succeeded = ?, n_errored = ?, cost_usd = ?, note = ? WHERE id = ?""",
            (
                self._clock().isoformat(timespec="seconds"),
                "limit" if report.limit_hit else "ended",
                report.calls,
                report.succeeded,
                report.failed,
                report.cost_estimate_usd,
                report.stopped_reason,
                report.batch_id,
            ),
        )
        self.conn.commit()

    def _upsert_extraction(
        self, req: ExtractionRequest, batch_id: str, status: str, **fields: object
    ) -> None:
        cid = req.custom_id(self.ecfg.batch.custom_id_prefix)
        now_iso = self._clock().isoformat(timespec="seconds")
        self.conn.execute(
            """INSERT INTO extraction(story_id, prompt_version, model_tier, custom_id, batch_id, status, stratum, escalation_reason, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(story_id, prompt_version, model_tier) DO UPDATE SET batch_id = excluded.batch_id, status = excluded.status, updated_at = excluded.updated_at""",
            (
                req.story_id,
                str(req.prompt_version),
                req.model_tier,
                cid,
                batch_id,
                status,
                req.stratum,
                req.escalation_reason,
                now_iso,
                now_iso,
            ),
        )
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            self.conn.execute(
                f"UPDATE extraction SET {cols}, updated_at = ? WHERE story_id = ? AND prompt_version = ? AND model_tier = ?",  # noqa: S608 - column names are ours
                (*fields.values(), now_iso, req.story_id, str(req.prompt_version), req.model_tier),
            )
        self.conn.commit()

    # --- one story ---------------------------------------------------------------------------------------
    def _dump_failure(self, req: ExtractionRequest, res: HeadlessResult, err: str) -> None:
        """Keep the raw harness output of a failed call under logs/extract_failures/ (gitignored) so schema and
        harness errors can be inspected without spending another call."""
        try:
            out_dir = self.limit_stamp.parent / "extract_failures"  # logs/ in production, tmp_path in tests
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = self._clock().strftime("%Y%m%dT%H%M%S")
            payload = {
                "story_id": req.story_id,
                "prompt_version": req.prompt_version,
                "model_tier": req.model_tier,
                "error": err,
                "subtype": res.subtype,
                "usage": res.usage,
                "structured": res.structured,
                "raw": res.raw,
                "stderr": res.stderr,
            }
            (out_dir / f"{req.story_id}_{req.model_tier}_{stamp}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass

    def _call(self, story: StoryInput, tier: TierName) -> HeadlessResult:
        argv, _user = build_extract_cmd(story, self.prompt, tier, extract_cfg=self.ecfg, models_cfg=self.mcfg)
        cmd = default_run_cmd() if self.run_cmd is _DEFAULT_SENTINEL else self.run_cmd
        out, err, rc = cmd(argv)
        return parse_claude_json(out, err, rc)

    def extract_story(
        self,
        story: StoryInput,
        tier: TierName,
        batch_id: str,
        report: RunReport,
        escalation_reason: str | None = None,
    ) -> ExtractionOutcome:
        req = ExtractionRequest(story.story_id, self.prompt.version, tier, story.stratum, escalation_reason)
        self._upsert_extraction(req, batch_id, "submitted")
        attempts = 0
        last: HeadlessResult | None = None
        last_err: str | None = None
        while attempts < 2:
            attempts += 1
            report.calls += 1
            res = self._call(story, tier)
            last = res
            report.tokens_in += (
                res.usage["input_tokens"]
                + res.usage["cache_read_input_tokens"]
                + res.usage["cache_creation_input_tokens"]
            )
            report.tokens_out += res.usage["output_tokens"]
            report.cost_estimate_usd += res.cost_estimate_usd
            model = next(iter(res.model_usage.keys()), None)
            if res.limit_hit:
                self._mark_limit()
                report.limit_hit = True
                self._upsert_extraction(req, batch_id, "failed", error="limit", model=model)
                return ExtractionOutcome(req, "failed", error="limit")
            if res.is_error or res.structured is None:
                # The harness could not deliver a schema-valid object (max turns, structured-output retries,
                # transport error). Structured-output exhaustion counts as a schema failure for escalation.
                sub = res.subtype or "no_structured_output"
                prefix = "schema" if "structured_output" in sub or "max_turns" in sub else "harness"
                last_err = f"{prefix}: {res.error or sub}"
                self._dump_failure(req, res, last_err)
                self._upsert_extraction(req, batch_id, "submitted", error=last_err[:300])
                continue
            try:
                parsed = ExtractionResult.model_validate(res.structured)
            except ValidationError as exc:
                detail = "; ".join(
                    f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:4]
                )
                last_err = f"schema: {detail}"[:300]
                self._dump_failure(req, res, last_err)
                self._upsert_extraction(req, batch_id, "submitted", error=last_err)
                continue
            stats: PersistStats = persist_result(
                self.conn,
                story,
                parsed,
                extracted_by=f"{model or tier}@{self.prompt.version_tag}",
                now=self.now,
                aliases=self.aliases,
            )
            self._upsert_extraction(
                req,
                batch_id,
                "succeeded",
                result_json=parsed.model_dump_json(),
                tokens_in=res.usage["input_tokens"]
                + res.usage["cache_read_input_tokens"]
                + res.usage["cache_creation_input_tokens"],
                tokens_out=res.usage["output_tokens"],
                cost_usd=res.cost_estimate_usd,
                model=model,
                error=None,
            )
            report.succeeded += 1
            report.claims += stats.claims
            report.entities_new += stats.entities_new
            return ExtractionOutcome(
                req,
                "succeeded",
                result_json=parsed.model_dump_json(),
                tokens_in=report.tokens_in,
                tokens_out=report.tokens_out,
                model=model,
            )
        err = last_err or (last.error if last and last.error else None) or "no result"
        self._upsert_extraction(req, batch_id, "failed", error=err[:300])
        self.conn.execute(
            "UPDATE extraction SET attempts = attempts + 1 WHERE story_id = ? AND prompt_version = ? AND model_tier = ?",
            (req.story_id, str(req.prompt_version), req.model_tier),
        )
        self.conn.commit()
        report.failed += 1
        return ExtractionOutcome(req, "failed", error=err[:300])

    # --- a run -----------------------------------------------------------------------------------------
    def run(self, candidates: list[Candidate], *, max_calls: int | None = None) -> RunReport:
        t0 = time.monotonic()
        if os.environ.get("MACROWEB_DISABLE_LLM") and self.run_cmd is _DEFAULT_SENTINEL:
            raise RuntimeError(
                "MACROWEB_DISABLE_LLM is set: refusing to call claude -p (use --dry-run or a fake run_cmd)"
            )
        report = RunReport(batch_id=self._open_batch(), selected=len(candidates))
        cap_run = max_calls if max_calls is not None else self.ecfg.headless.calls_per_tick
        remaining_day = self.ecfg.headless.max_calls_per_day - self.calls_today()
        budget = max(0, min(cap_run, remaining_day))
        if self.limit_backoff_active():
            report.stopped_reason = f"limit backoff active ({self.limit_stamp.name})"
            budget = 0
        for cand in candidates:
            if report.calls >= budget:
                report.stopped_reason = report.stopped_reason or (
                    "daily cap reached" if remaining_day <= report.calls else "run cap reached"
                )
                break
            story = cand.story
            if len(story.text or "") < 60:
                report.skipped["no_text"] = report.skipped.get("no_text", 0) + 1
                continue
            tier = cand.forced_tier or self.router.tier_for_stratum(story.stratum)
            if tier is None:
                report.skipped["no_llm_stratum"] = report.skipped.get("no_llm_stratum", 0) + 1
                continue
            if cand.forced_tier:
                report.escalated += 1
            outcome = self.extract_story(
                story, tier, report.batch_id, report, escalation_reason=cand.escalation_reason
            )
            if report.limit_hit:
                report.stopped_reason = "subscription limit hit"
                break
            if outcome.status == "failed" and (outcome.error or "").startswith("schema"):
                nxt = self.router.escalate(tier)
                if (
                    nxt
                    and self.escalations_today() < self.mcfg.routing.escalation.daily_cap
                    and report.calls < budget
                ):
                    report.escalated += 1
                    self._upsert_extraction(
                        ExtractionRequest(story.story_id, self.prompt.version, tier, story.stratum),
                        report.batch_id,
                        "escalated",
                    )
                    self.extract_story(story, nxt, report.batch_id, report, escalation_reason="schema_fail")
        report.elapsed_s = time.monotonic() - t0
        self._close_batch(report)
        return report


def recent_extractions(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.story_id, e.model_tier, e.status, e.model, e.tokens_in, e.tokens_out, e.error, e.updated_at, s.title_rep
           FROM extraction e JOIN story s ON s.id = e.story_id ORDER BY e.updated_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
