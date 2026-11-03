"""Publish a gated weekly draft (PLAN §11): reports/<week>.md, a vault link note, a blog draft without the private
portfolio section, a report_citation row per cited claim, and a short notification (stdout + macOS + Telegram
when configured). Idempotent: re-publishing the same draft rewrites the same files."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from macroweb.paths import ROOT, digests_dir
from macroweb.synth.gate import CLAIM_REF

REPORTS_DIR = ROOT / "reports"
DRAFTS_DIR = ROOT / "drafts"
VAULT_WEEKLY = ROOT / "vault" / "weekly"
PORTFOLIO_HEADING = re.compile(r"^##\s*\(비공개\)")
HEADING = re.compile(r"^##\s")
ONE_LINER = re.compile(r"^\*\*한 줄:\*\*\s*(.+)$")
THESIS_ROW = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+)\|")


@dataclass
class PublishResult:
    report: Path
    blog: Path
    vault_note: Path
    one_liner: str
    theses: list[str]
    citations: int
    notified: str


def strip_portfolio(text: str) -> str:
    out, skipping = [], False
    for ln in text.splitlines():
        if PORTFOLIO_HEADING.match(ln):
            skipping = True
            continue
        if skipping and HEADING.match(ln):
            skipping = False
        if not skipping:
            out.append(ln)
    return "\n".join(out) + "\n"


def summary_bits(text: str) -> tuple[str, list[str]]:
    one, theses = "", []
    in_board = False
    for ln in text.splitlines():
        m = ONE_LINER.match(ln.strip())
        if m and not one:
            one = m.group(1).strip()
        if ln.startswith("## 논제 보드"):
            in_board = True
            continue
        if in_board and HEADING.match(ln):
            in_board = False
        if in_board:
            r = THESIS_ROW.match(ln)
            if r and "논제" not in r.group(1):
                theses.append(r.group(1).strip())
    return one, theses[:3]


def publish_report(
    conn: sqlite3.Connection,
    week: str,
    draft: Path,
    *,
    reports_dir: Path | None = None,
    drafts_dir: Path | None = None,
    vault_dir: Path | None = None,
    notify: bool = True,
) -> PublishResult:
    text = draft.read_text(encoding="utf-8")
    rdir, ddir, vdir = reports_dir or REPORTS_DIR, drafts_dir or DRAFTS_DIR, vault_dir or VAULT_WEEKLY
    for d in (rdir, ddir, vdir):
        d.mkdir(parents=True, exist_ok=True)
    report = rdir / f"{week}.md"
    report.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    blog = ddir / f"blog-{week}.md"
    blog.write_text(strip_portfolio(text), encoding="utf-8")
    one, theses = summary_bits(text)
    cids = sorted(set(CLAIM_REF.findall(text)))
    conn.execute("DELETE FROM report_citation WHERE report_week = ? AND section = 'body'", (week,))
    conn.executemany(
        "INSERT INTO report_citation(report_week, claim_id, relation_id, section) VALUES (?, ?, NULL, 'body')",
        [(week, cid) for cid in cids],
    )
    conn.commit()
    note = vdir / f"{week}.md"
    note.write_text(
        "\n".join(
            [
                f"# 거미줄 리포트 {week}",
                "",
                f"**한 줄:** {one or '-'}",
                "",
                f"- 리포트: [[../../reports/{week}.md]]",
                f"- 블로그 초안: [[../../drafts/blog-{week}.md]]",
                f"- 일일 다이제스트: {digests_dir().name}/",
                "",
                "## 논제",
                *([f"- {t}" for t in theses] or ["- (없음)"]),
                "",
                "## 인용 claim",
                *([f"- `{c}`" for c in cids[:50]] or ["- (없음)"]),
                "",
                f"> 발행 {datetime.now(UTC).isoformat(timespec='minutes')} · 투자 자문 아님",
            ]
        ),
        encoding="utf-8",
    )
    notified = "skipped"
    if notify:
        from macroweb.publish.notify import notify as _notify

        msg = "\n".join([f"거미줄 {week} 발행", one or "", *[f"• {t}" for t in theses], str(report)])
        notified = str(_notify("info", "weekly", msg, 0, None))
    return PublishResult(
        report=report,
        blog=blog,
        vault_note=note,
        one_liner=one,
        theses=theses,
        citations=len(cids),
        notified=notified,
    )
