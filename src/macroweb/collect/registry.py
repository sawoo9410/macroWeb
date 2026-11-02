"""Source registry (config/sources.yaml) and HTTP probes used by `macroweb source probe` and
`make doctor-full`. Probes never send credentials; keyed APIs expose a `probe_url` that answers without a key."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import httpx

from macroweb.collect.politeness import USER_AGENT, DomainThrottle
from macroweb.collect.robots import RobotsCache
from macroweb.config import Source, load_sources


@dataclass
class ProbeResult:
    id: str
    tier: int
    ok: bool
    status: int | None
    final_url: str | None
    content_type: str | None
    elapsed_ms: int
    error: str | None = None
    note: str | None = None
    robots: str | None = None  # allowed | disallowed | unknown (ADR-0005: API 소스도 robots 를 따른다)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def list_sources(enabled_only: bool = False) -> list[Source]:
    sources = load_sources().sources
    return [s for s in sources if s.enabled] if enabled_only else sources


def probe_source(
    src: Source, client: httpx.Client | None = None, timeout: float = 15.0, robots: RobotsCache | None = None
) -> ProbeResult:
    url = src.probe_url or src.url
    own = client is None
    client = client or httpx.Client(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    t0 = time.monotonic()
    try:
        resp = None
        if src.kind not in ("api", "json"):  # APIs often loop HEAD through redirects; fetch them directly
            try:
                resp = client.head(url)
            except httpx.TooManyRedirects:
                resp = None
        if resp is None or resp.status_code >= 400:  # many sites reject HEAD; retry with a bounded GET
            with client.stream("GET", url) as r:
                for _ in r.iter_bytes(chunk_size=65536):
                    break
                resp = r
        ms = int((time.monotonic() - t0) * 1000)
        auth_gate = bool(src.auth_env) and 400 <= resp.status_code < 500
        robots_state = (robots or RobotsCache(client)).check(url)
        return ProbeResult(
            id=src.id,
            tier=src.tier,
            ok=resp.status_code < 400 or auth_gate,
            status=resp.status_code,
            final_url=str(resp.url),
            content_type=resp.headers.get("content-type", "")[:60],
            elapsed_ms=ms,
            note="reachable; key required (expected without " + str(src.auth_env) + ")"
            if auth_gate
            else None,
            robots=robots_state,
        )
    except httpx.HTTPError as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return ProbeResult(src.id, src.tier, False, None, None, None, ms, error=type(exc).__name__)
    finally:
        if own:
            client.close()


def probe_all(enabled_only: bool = True, timeout: float = 15.0) -> list[ProbeResult]:
    throttle = DomainThrottle()
    results: list[ProbeResult] = []
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        robots = RobotsCache(client)
        for src in list_sources(enabled_only=enabled_only):
            throttle.wait(src.probe_url or src.url)
            results.append(probe_source(src, client=client, timeout=timeout, robots=robots))
    return results


def probe_markdown(results: list[ProbeResult]) -> str:
    lines = ["| id | tier | ok | status | robots | ms | final_url / error |", "|---|---|---|---|---|---|---|"]
    for r in results:
        tail = r.error or r.note or (r.final_url or "")
        lines.append(
            f"| {r.id} | T{r.tier} | {'✅' if r.ok else '❌'} | {r.status or '-'} | {r.robots or '-'} | {r.elapsed_ms} | {tail[:90]} |"
        )
    return "\n".join(lines)
