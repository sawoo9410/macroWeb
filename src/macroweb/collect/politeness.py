"""Scraping etiquette (PLAN §0.1-7): one connection per domain, >= 2 s between hits, declared UA.
robots.txt handling arrives with the fetchers in Phase 1."""

from __future__ import annotations

import time
from urllib.parse import urlsplit

# 연락처·레포 URL 포함 여부는 docs/QUESTIONS.md Q4 (사용자 결정 전까지 일반 문자열).
USER_AGENT = "Mozilla/5.0 (compatible; macroweb-collector/0.1)"
MIN_INTERVAL_S = 2.0


def domain_of(url: str) -> str:
    return urlsplit(url).netloc.lower()


class DomainThrottle:
    def __init__(self, min_interval_s: float = MIN_INTERVAL_S) -> None:
        self.min_interval_s = min_interval_s
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> float:
        dom = domain_of(url)
        now = time.monotonic()
        delay = max(0.0, self._last.get(dom, -1e9) + self.min_interval_s - now)
        if delay > 0:
            time.sleep(delay)
        self._last[dom] = time.monotonic()
        return delay
