"""Cheap language detection for routing (ko / en / other). PLAN §4.3 allows langdetect/fasttext; a script
heuristic is enough for Korean vs English headlines and avoids a model download in Phase 1."""

from __future__ import annotations

import re

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")
_CJK = re.compile(r"[一-鿿぀-ヿ]")


def detect_lang(text: str | None, default: str = "en", min_letters: int = 4) -> str:
    if not text:
        return default
    sample = text[:2000]
    hangul = len(_HANGUL.findall(sample))
    latin = len(_LATIN.findall(sample))
    cjk = len(_CJK.findall(sample))
    total = hangul + latin + cjk
    if total < min_letters:
        return default
    if hangul / total >= 0.2:
        return "ko"
    if cjk / total >= 0.3:
        return "other"
    return "en" if latin / total >= 0.5 else default
