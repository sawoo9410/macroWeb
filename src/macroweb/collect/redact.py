"""Never let an API key reach disk or logs: strip credential query params and replace known secret values
before a URL is written to raw meta, fixtures, fetch_log or notifications."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CREDENTIAL_PARAMS = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "auth",
    "authkey",
    "serviceKey",
    "crtfc_key",
}


def redact_url(url: str, secrets: list[str] | None = None) -> str:
    parts = urlsplit(url)
    query = [
        (k, "<redacted>" if k in CREDENTIAL_PARAMS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    out = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))
    for sec in secrets or []:
        if sec and len(sec) >= 6:
            out = out.replace(sec, "<redacted>")
    return out
