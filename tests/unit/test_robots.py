import httpx

from macroweb.collect.http import make_client
from macroweb.collect.robots import RobotsCache


def _client(status: int, body: str = "") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(status, text=body)
        return httpx.Response(200, text="ok")

    return make_client(transport=httpx.MockTransport(handler))


def test_robots_tri_state() -> None:
    assert RobotsCache(_client(404)).check("https://x.test/api/a") == "allowed"
    assert (
        RobotsCache(_client(200, "User-agent: *\nDisallow: /\n")).check("https://x.test/api/a")
        == "disallowed"
    )
    assert (
        RobotsCache(_client(200, "User-agent: *\nDisallow: /private/\n")).check("https://x.test/api/a")
        == "allowed"
    )
    assert RobotsCache(_client(401)).check("https://x.test/api/a") == "unknown"
    cache = RobotsCache(_client(500))
    assert cache.check("https://x.test/a") == "unknown" and not cache.allowed("https://x.test/a")
