"""Duplicate detection, stage 1–2 of PLAN §4.3: URL canonicalisation and title SimHash (Hamming <= 3 is the
start value, to be recalibrated on 200 labelled pairs at the end of Phase 1 — PLAN §0.4). Stage 3
(embedding cosine) arrives with bge-m3 in Phase 2."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "dclid",
    "igshid",
    "ref",
    "ref_src",
    "cmpid",
    "ncid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "spm",
    "oc",
    "source",
    "ocid",
    "sref",
    "ftag",
    "smid",
    "mod",
    "cid",
    "partner",
    "yclid",
    "mkt_tok",
    "s_cid",
}
_TITLE_NOISE = re.compile(
    r"^\s*(\[[^\]]{1,12}\]|\([^)]{1,12}\)|breaking:|속보:|단독:|종합:|update\s*\d*:)\s*", re.IGNORECASE
)
_TITLE_TAIL = re.compile(
    r"\s*(\((종합|상보|속보|[1-3]보|updated?\s*\d*|update\s*\d*)\)|\[(종합|상보|updated?\s*\d*)\])\s*$",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
_HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
_CJK = re.compile(r"[一-鿿぀-ヿ]")
_WORD = re.compile(r"[a-z0-9]+")


def canonical_url(url: str) -> str:
    """Lower-case host, drop fragment/tracking params/default ports/AMP markers, sort query, trim trailing slash."""
    url = url.strip()
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    host = parts.hostname or ""
    host = host.lower()
    if host.startswith("amp."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/+", "/", parts.path or "/")
    if path.endswith("/amp") or path.endswith("/amp/"):
        path = path[: path.rfind("/amp")] or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def article_id(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def title_norm(title: str) -> str:
    t = title.strip()
    for _ in range(3):
        t2 = _TITLE_NOISE.sub("", t)
        if t2 == t:
            break
        t = t2
    t = _TITLE_TAIL.sub("", t)
    t = t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    t = _WS.sub(" ", t).strip().lower()
    return t


def tokens_for_simhash(text: str) -> list[str]:
    """Words for Latin text, character bigrams for Hangul/CJK runs (word boundaries are unreliable there)."""
    t = title_norm(text)
    out: list[str] = []
    buf = ""
    for ch in t + " ":
        if _HANGUL.match(ch) or _CJK.match(ch):
            buf += ch
            continue
        if buf:
            out.extend(buf[i : i + 2] for i in range(max(1, len(buf) - 1)))
            buf = ""
    latin = " ".join(_WORD.findall(t))
    if len(latin) >= 3:
        out.extend(latin[i : i + 3] for i in range(len(latin) - 2))
    else:
        out.extend(_WORD.findall(t))
    return out or [t]


def simhash64(text: str) -> int:
    vec = [0] * 64
    for tok in tokens_for_simhash(text):
        h = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:8], "big")  # noqa: S324 - not security
        for i in range(64):
            vec[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, v in enumerate(vec):
        if v > 0:
            out |= 1 << i
    return out


def simhash_hex(text: str) -> str:
    return f"{simhash64(text):016x}"


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def hamming_hex(a: str, b: str) -> int:
    return hamming(int(a, 16), int(b, 16))
