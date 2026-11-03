"""Deterministic fact-check gate (PLAN §7.3, §10.2 step 6, 부록 F): the Python half of the fact-checker.
Every `[F]` sentence must cite an active VERIFIED/CORROBORATED claim, numbers in it must match the claim within
config/tolerances.yaml, forbidden trading language fails, quarantined labels may appear only in the verification
notes, and the private portfolio section may not carry amounts. The LLM fact-checker agent runs on top of this
in the editorial skill; publishing requires this gate to PASS."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from macroweb.verify.signals import tolerances, unit_family

FACT_LABELS = ("VERIFIED", "CORROBORATED")
QUARANTINE_LABELS = ("DEBUNKED", "RECYCLED", "SPAM_SATIRE")
CLAIM_REF = re.compile(r"\[([0-9a-f]{16})\]")
F_MARK = re.compile(r"\[F\]")
FORBIDDEN = re.compile(  # trading *instructions* only — "순매도", "매수세" and other descriptive uses are fine
    r"((?<!순)매[수도]\s*(하라|하세요|추천|권고|의견|해야|할\s*때|타이밍)|비중\s*(확대|축소)|헤지하라|환노출하라"
    r"|(?<![가-힣])사라(?![가-힣])|팔아라|\b(buy|sell)\s+(now|recommendation|rating|signal)s?\b|\b(strong\s+)?(buy|sell)\s+rating\b)",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+]?\d+(?:\.\d+)?")
AMOUNT = re.compile(r"\d[\d,\.]*\s*(원|달러|\$|주|USD|KRW|억|만)")
NOTES_HEADING = re.compile(r"^##\s*검증 노트")
PORTFOLIO_HEADING = re.compile(r"^##\s*\(비공개\)")
HEADING = re.compile(r"^##\s")


@dataclass
class Violation:
    rule: str
    line: int
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "line": self.line, "detail": self.detail}


@dataclass
class GateResult:
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    n_fact_sentences: int = 0
    n_citations: int = 0
    n_checked_numbers: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "pass": self.passed,
            "violations": [v.as_dict() for v in self.violations],
            "n_fact_sentences": self.n_fact_sentences,
            "n_citations": self.n_citations,
            "n_checked_numbers": self.n_checked_numbers,
        }

    def render(self) -> str:
        head = f"GATE {'PASS' if self.passed else 'FAIL'} — [F] {self.n_fact_sentences}, citations {self.n_citations}, numbers checked {self.n_checked_numbers}, violations {len(self.violations)}"
        return "\n".join([head, *(f"  L{v.line} {v.rule}: {v.detail}" for v in self.violations)])


def _sections(lines: list[str]) -> list[str]:
    """Section name per line ('notes', 'portfolio', or 'body')."""
    out, cur = [], "body"
    for ln in lines:
        if NOTES_HEADING.match(ln):
            cur = "notes"
        elif PORTFOLIO_HEADING.match(ln):
            cur = "portfolio"
        elif HEADING.match(ln):
            cur = "body"
        out.append(cur)
    return out


def _numbers(text: str) -> list[float]:
    vals = []
    for m in NUMBER.finditer(text):
        tok = m.group(0).replace(",", "")
        try:
            vals.append(float(tok))
        except ValueError:
            continue
    return vals


def check_draft(conn: sqlite3.Connection, text: str, *, errata_required: bool = False) -> GateResult:
    res = GateResult(passed=True)
    lines = text.splitlines()
    sections = _sections(lines)
    tol = tolerances()
    claim_cache: dict[str, sqlite3.Row | None] = {}

    def claim(cid: str) -> sqlite3.Row | None:
        if cid not in claim_cache:
            claim_cache[cid] = conn.execute(
                "SELECT id, label, status, value, unit, text FROM claim WHERE id = ?", (cid,)
            ).fetchone()
        return claim_cache[cid]

    for i, (ln, sec) in enumerate(zip(lines, sections, strict=True), 1):
        if sec != "notes" and FORBIDDEN.search(ln) and not ln.lstrip().startswith(">"):
            res.violations.append(Violation("forbidden_phrase", i, FORBIDDEN.search(ln).group(0)))  # type: ignore[union-attr]
        if sec == "portfolio" and AMOUNT.search(ln):
            res.violations.append(Violation("portfolio_amount", i, AMOUNT.search(ln).group(0)))  # type: ignore[union-attr]
        refs = CLAIM_REF.findall(ln)
        is_fact = bool(F_MARK.search(ln))
        if is_fact:
            res.n_fact_sentences += 1
            if not refs:
                res.violations.append(Violation("fact_without_claim_id", i, ln.strip()[:80]))
        for cid in refs:
            res.n_citations += 1
            row = claim(cid)
            if row is None:
                res.violations.append(Violation("unknown_claim_id", i, cid))
                continue
            if row["status"] != "active":
                res.violations.append(Violation("claim_not_active", i, f"{cid} status={row['status']}"))
            if row["label"] in QUARANTINE_LABELS and sec != "notes":
                res.violations.append(Violation("quarantined_label_in_body", i, f"{cid} {row['label']}"))
            if is_fact and row["label"] not in FACT_LABELS:
                res.violations.append(Violation("label_too_weak_for_F", i, f"{cid} {row['label']}"))
            if is_fact and row["value"] is not None:
                nums = _numbers(F_MARK.sub("", CLAIM_REF.sub("", ln)))
                if nums:
                    res.n_checked_numbers += 1
                    fam = unit_family(row["unit"]) or "index"
                    t = tol.by_unit.get({"%": "%", "bp": "bp", "KRW": "KRW", "USD": "USD"}.get(fam, "index"))
                    value = float(row["value"])
                    allow = (
                        float(t.abs)
                        if (t and t.abs is not None)
                        else float(t.rel if (t and t.rel is not None) else tol.default_rel) * abs(value)
                    )
                    if not any(abs(n - value) <= max(allow, 1e-9) for n in nums):
                        res.violations.append(
                            Violation(
                                "number_mismatch",
                                i,
                                f"{cid} claim={value}{row['unit'] or ''} sentence={nums[:4]}",
                            )
                        )
    if errata_required and not any(ln.startswith("## 정정") for ln in lines):
        res.violations.append(
            Violation(
                "errata_section_missing",
                0,
                "quality review lists corrections but the report has no 정정 section",
            )
        )
    res.passed = not res.violations
    return res
