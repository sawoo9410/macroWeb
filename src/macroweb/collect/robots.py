"""robots.txt check for article-body fetches (PLAN §0.1-7). One fetch per host per process; 404 means no
rules (allow), network errors are treated as disallow so a flaky host never gets scraped by accident."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from macroweb.collect.politeness import USER_AGENT


class RobotsCache:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self._cache: dict[str, RobotFileParser | None] = {}

    def _load(self, host_url: str) -> RobotFileParser | None:
        parts = urlsplit(host_url)
        key = f"{parts.scheme}://{parts.netloc}"
        if key in self._cache:
            return self._cache[key]
        rp = RobotFileParser()
        try:
            r = self.client.get(urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", "")))
            if r.status_code == 404:
                rp.parse([])
            elif r.status_code >= 400:
                self._cache[key] = None
                return None
            else:
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            self._cache[key] = None
            return None
        self._cache[key] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._load(url)
        if rp is None:
            return False
        return rp.can_fetch(USER_AGENT, url)
