"""Thin Anthropic SDK wrapper. Two paths: real-time structured completion (`complete_json`) and the
Message Batches API (`batch_request` / `submit_batch` / `iter_batch_results`) used for rolling overnight
extraction (PLAN §0.3 배치 타이밍). The SDK resolves `ANTHROPIC_API_KEY` from the environment; the key is
never read or logged here. Live calls start in Phase 2."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from macroweb.config import TierName
from macroweb.llm.router import ModelRouter, Usage
from macroweb.llm.schemas import strict_json_schema

T = TypeVar("T", bound=BaseModel)


class LLMRefusal(RuntimeError):
    """The model declined (stop_reason == 'refusal'). Callers quarantine the Story and move on."""


@dataclass
class Completion:
    parsed: Any
    usage: Usage
    model: str
    cost_usd: float
    stop_reason: str | None


def _usage_from(resp: Any) -> Usage:
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage()
    return Usage(
        input_tokens=int(getattr(u, "input_tokens", 0) or 0),
        output_tokens=int(getattr(u, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    )


class LLMClient:
    def __init__(self, router: ModelRouter | None = None, client: Any | None = None) -> None:
        self.router = router or ModelRouter()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic  # imported lazily so `macroweb --help` stays fast and offline

            self._client = anthropic.Anthropic()
        return self._client

    @staticmethod
    def _system_blocks(system: str, cache: bool) -> list[dict[str, Any]]:
        block: dict[str, Any] = {"type": "text", "text": system}
        if cache:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def complete_json(
        self,
        *,
        tier: TierName,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 4096,
        effort: str | None = None,
        cache_system: bool = True,
    ) -> Completion:
        """Real-time structured output validated into `schema` (for post-deadline Stories, §0.3)."""
        model = self.router.model_id(tier)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": self._system_blocks(system, cache_system),
            "messages": [{"role": "user", "content": user}],
            "output_format": schema,
        }
        kwargs["output_config"] = {"effort": effort or self.router.effort(tier)}
        resp = self.client.messages.parse(**kwargs)
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            raise LLMRefusal(f"{model} refused ({getattr(resp, 'stop_details', None)})")
        usage = _usage_from(resp)
        return Completion(
            parsed=resp.parsed_output,
            usage=usage,
            model=model,
            cost_usd=self.router.estimate_cost(tier, usage),
            stop_reason=stop,
        )

    def batch_request(
        self,
        custom_id: str,
        *,
        tier: TierName,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int = 4096,
        effort: str | None = None,
        cache_system: bool = True,
    ) -> Any:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        params: dict[str, Any] = {
            "model": self.router.model_id(tier),
            "max_tokens": max_tokens,
            "system": self._system_blocks(system, cache_system),
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": effort or self.router.effort(tier),
                "format": {"type": "json_schema", "schema": strict_json_schema(schema)},
            },
        }
        return Request(custom_id=custom_id, params=cast(MessageCreateParamsNonStreaming, params))

    def submit_batch(self, requests: list[Any]) -> str:
        batch = self.client.messages.batches.create(requests=requests)
        return str(batch.id)

    def batch_status(self, batch_id: str) -> dict[str, Any]:
        b = self.client.messages.batches.retrieve(batch_id)
        counts = getattr(b, "request_counts", None)
        return {
            "id": b.id,
            "processing_status": b.processing_status,
            "succeeded": getattr(counts, "succeeded", None),
            "errored": getattr(counts, "errored", None),
            "processing": getattr(counts, "processing", None),
        }

    def iter_batch_results(self, batch_id: str) -> Iterator[Any]:
        """Yields raw result objects; results arrive in any order, so key by `custom_id`."""
        yield from self.client.messages.batches.results(batch_id)
