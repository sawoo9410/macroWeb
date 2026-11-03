"""Extraction eval set (PLAN §6.3 · §6.2.4): 30 stories, Korean/English half and half, human labels in
eval/extraction/labels/<story_id>.yaml, scored against the claims the pipeline stored (or against one tier's
ledger result for the routing experiment). The repo keeps ids, titles, URLs and a short preview — full texts
stay in the local DB (`macroweb eval extract show <story_id>`), so no article body is committed."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from macroweb.config import load_extract
from macroweb.extract.select import _themes, theme_similarity
from macroweb.paths import ROOT

EVAL_DIR = ROOT / "eval" / "extraction"
QUOTA: dict[tuple[str, str], int] = {  # 30 = 15 ko + 15 en; every LLM stratum represented
    ("S-T1-KO", "ko"): 10,
    ("S-T0-STMT", "ko"): 5,
    ("S-T0-STMT", "en"): 5,
    ("S-T0-LONG", "en"): 4,
    ("S-T2", "en"): 4,
    ("S-T1", "en"): 2,
}
MIN_CHARS_DEFAULT = 400
MIN_CHARS_BY_STRATUM = {"S-T1": 150}  # English wire feeds arrive as title + description only
PER_SOURCE_CAP = 4
TEXT_MATCH_JACCARD = 0.5
NUMERIC_REL_TOL = 0.01
_HANGUL = re.compile(r"[가-힣]")
_WORD = re.compile(r"[a-z0-9][a-z0-9.%,-]*")


def stories_path(eval_dir: Path = EVAL_DIR) -> Path:
    return eval_dir / "stories.jsonl"


def labels_dir(eval_dir: Path = EVAL_DIR) -> Path:
    return eval_dir / "labels"


def results_dir(eval_dir: Path = EVAL_DIR) -> Path:
    return eval_dir / "results"


# --- building the set -----------------------------------------------------------------------------------
def _candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT s.id, s.title_rep, s.first_seen, src.id AS source_id, src.stratum, src.lang AS src_lang,
                  a.lang, a.url, a.published_at,
                  LENGTH(COALESCE(NULLIF(a.text, ''), a.summary, '')) AS n_chars,
                  SUBSTR(COALESCE(NULLIF(a.text, ''), a.summary, ''), 1, 1500) AS probe,
                  s.n_independent,
                  (s.selected_at IS NOT NULL) AS selected,
                  (SELECT COUNT(*) FROM claim c WHERE c.story_id = s.id) AS n_claims
           FROM story s
           JOIN article a ON a.id = COALESCE(s.rep_article_id,
                (SELECT sa.article_id FROM story_article sa WHERE sa.story_id = s.id ORDER BY sa.is_syndicated LIMIT 1))
           JOIN source src ON src.id = a.source_id
           WHERE src.stratum IS NOT NULL AND src.enabled = 1
           ORDER BY n_claims DESC, selected DESC, a.published_at DESC"""
    ).fetchall()


def pick_stories(
    conn: sqlite3.Connection,
    *,
    quota: dict[tuple[str, str], int] | None = None,
    min_chars: int = MIN_CHARS_DEFAULT,
    per_source_cap: int = PER_SOURCE_CAP,
) -> list[dict[str, Any]]:
    """Fill each (stratum, lang) bucket: already-extracted stories first (so labels can be scored at once), then
    stories the selector passed (theme gate), then newest; at most `per_source_cap` per source per bucket."""
    quota = dict(quota or QUOTA)
    themes = _themes()
    sel = load_extract().selection
    taken: dict[tuple[str, str], int] = defaultdict(int)
    per_source: dict[tuple[str, str, str], int] = defaultdict(int)
    out: list[dict[str, Any]] = []
    for r in _candidates(conn):
        lang = (
            r["lang"]
            if r["lang"] in ("ko", "en")
            else (r["src_lang"] if r["src_lang"] in ("ko", "en") else None)
        )
        if lang is None:
            continue
        key = (r["stratum"], lang)
        if key not in quota or taken[key] >= quota[key]:
            continue
        if int(r["n_chars"] or 0) < MIN_CHARS_BY_STRATUM.get(r["stratum"], min_chars):
            continue
        if per_source[(key[0], key[1], r["source_id"])] >= per_source_cap:
            continue
        if not r["stratum"].startswith(
            "S-T0"
        ):  # same theme gate the live selector applies to news (not primary docs)
            sim, _theme = theme_similarity(f"{r['title_rep']} {r['probe'] or ''}", themes)
            if sim < sel.min_theme_score and int(r["n_independent"] or 1) < sel.min_independent_to_force:
                continue
        taken[key] += 1
        per_source[(key[0], key[1], r["source_id"])] += 1
        out.append(
            {
                "story_id": r["id"],
                "source_id": r["source_id"],
                "stratum": r["stratum"],
                "lang": lang,
                "title": r["title_rep"],
                "url": r["url"],
                "published_at": r["published_at"],
                "text_chars": int(r["n_chars"] or 0),
                "extracted": bool(r["n_claims"]),
            }
        )
    order = list(quota)
    out.sort(key=lambda d: (order.index((d["stratum"], d["lang"])), d["published_at"] or ""))
    return out


def story_text(conn: sqlite3.Connection, story_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT s.id, s.title_rep, a.source_id, a.url, a.published_at, a.lang,
                  COALESCE(NULLIF(a.text, ''), a.summary, '') AS text
           FROM story s JOIN article a ON a.id = COALESCE(s.rep_article_id,
                (SELECT sa.article_id FROM story_article sa WHERE sa.story_id = s.id ORDER BY sa.is_syndicated LIMIT 1))
           WHERE s.id = ?""",
        (story_id,),
    ).fetchone()
    return dict(row) if row else None


LABEL_TEMPLATE = """# 라벨 지침: eval/extraction/README.md — 원문 문장 그대로, 한 항목 = 한 사실, 기사가 말하지 않은 것은 쓰지 않는다.
# 본문 보기: uv run macroweb eval extract show {story_id}
story_id: {story_id}
source_id: {source_id}
stratum: {stratum}
lang: {lang}
title: {title}
url: {url}
labeler: null            # "sangwoo" | "opus" — null 이면 채점에서 제외
claims: []               # 예시 (주석을 풀어 채운다)
#  - text: "The Governing Council decided to keep the three key ECB interest rates unchanged."
#    type: event           # numeric | event | quote | forecast | attribution
#    value: null           # 숫자 claim 만: 3.75 (단위는 unit 에)
#    unit: null            # "%", bp, 조원, USD, QoQ, YoY ...
#    time_ref: "2026-10-29"
#    anonymous_source: false
relations: []            # 선택: - {{src: Lagarde, dst: ECB, type: reports_to, sign: 0}}
notes: ""
"""


def build(
    conn: sqlite3.Connection, *, eval_dir: Path = EVAL_DIR, force: bool = False, **pick_kw: Any
) -> list[dict[str, Any]]:
    """Write stories.jsonl (kept stable unless --force) and one label template per story (never overwritten)."""
    path = stories_path(eval_dir)
    if path.exists() and not force:
        stories = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        stories = pick_stories(conn, **pick_kw)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in stories), encoding="utf-8")
    ldir = labels_dir(eval_dir)
    ldir.mkdir(parents=True, exist_ok=True)
    for s in stories:
        target = ldir / f"{s['story_id']}.yaml"
        if target.exists():
            continue
        safe_title = json.dumps(s.get("title") or "", ensure_ascii=False)
        target.write_text(
            LABEL_TEMPLATE.format(
                story_id=s["story_id"],
                source_id=s["source_id"],
                stratum=s["stratum"],
                lang=s["lang"],
                title=safe_title,
                url=json.dumps(s.get("url") or "", ensure_ascii=False),
            ),
            encoding="utf-8",
        )
    return stories


# --- scoring ---------------------------------------------------------------------------------------------
def load_labels(eval_dir: Path = EVAL_DIR) -> list[dict[str, Any]]:
    out = []
    for p in sorted(labels_dir(eval_dir).glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if d.get("labeler") and isinstance(d.get("claims"), list) and d["claims"]:
            d["_path"] = str(p)
            out.append(d)
    return out


def norm_tokens(text: str) -> set[str]:
    """Hangul → character bigrams, Latin/digits → words; robust to particles and word order."""
    t = (text or "").lower()
    toks: set[str] = set(_WORD.findall(t))
    runs = re.findall(r"[가-힣]+", t)
    for run in runs:
        if len(run) == 1:
            toks.add(run)
        toks.update(run[i : i + 2] for i in range(len(run) - 1))
    return toks


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def numeric_equal(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(NUMERIC_REL_TOL * abs(a), 1e-9)


@dataclass
class StoryScore:
    story_id: str
    stratum: str
    lang: str
    n_labels: int
    n_preds: int
    tp: int = 0
    numeric_labels: int = 0
    numeric_wrong: int = 0
    matched: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / self.n_preds if self.n_preds else 0.0

    @property
    def recall(self) -> float:
        return self.tp / self.n_labels if self.n_labels else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def score_story(label: dict[str, Any], preds: list[dict[str, Any]]) -> StoryScore:
    """Greedy one-to-one matching by text Jaccard (≥ 0.5); numeric labels also match on value (±1 %).
    Numeric error = a numeric label matched by text whose predicted value is missing or different."""
    labels = [c for c in label.get("claims", []) if isinstance(c, dict) and c.get("text")]
    sc = StoryScore(
        story_id=label["story_id"],
        stratum=str(label.get("stratum") or "?"),
        lang=str(label.get("lang") or "?"),
        n_labels=len(labels),
        n_preds=len(preds),
    )
    used: set[int] = set()
    pred_tokens = [norm_tokens(p.get("text") or "") for p in preds]
    for lc in labels:
        ltoks = norm_tokens(lc["text"])
        raw_val = lc.get("value")
        lval: float | None = float(raw_val) if isinstance(raw_val, (int, float)) else None
        best, best_j = -1, 0.0
        for i, p in enumerate(preds):
            if i in used:
                continue
            j = jaccard(ltoks, pred_tokens[i])
            if lval is not None and numeric_equal(lval, p.get("value")) and j >= 0.2:
                j = max(j, 1.0)
            if j > best_j:
                best, best_j = i, j
        is_numeric = lval is not None
        sc.numeric_labels += int(is_numeric)
        if best >= 0 and best_j >= TEXT_MATCH_JACCARD:
            used.add(best)
            sc.tp += 1
            sc.matched.append((lc["text"], preds[best].get("text") or "", round(best_j, 3)))
            if lval is not None and not numeric_equal(lval, preds[best].get("value")):
                sc.numeric_wrong += 1
    return sc


def predictions(
    conn: sqlite3.Connection, story_id: str, *, tier: str | None = None, prompt_version: int | None = None
) -> list[dict[str, Any]]:
    """Claims to score: the stored claim table (default), or one tier's ledger result (routing experiment)."""
    if tier:
        where = "story_id = ? AND model_tier = ? AND status = 'succeeded' AND result_json IS NOT NULL"
        args: list[object] = [story_id, tier]
        if prompt_version is not None:
            where += " AND prompt_version = ?"
            args.append(str(prompt_version))
        row = conn.execute(
            f"SELECT result_json FROM extraction WHERE {where} ORDER BY updated_at DESC LIMIT 1",  # noqa: S608
            args,
        ).fetchone()
        if not row:
            return []
        return [dict(c) for c in (json.loads(row["result_json"]).get("claims") or [])]
    rows = conn.execute(
        "SELECT text, type, value, unit, time_ref FROM claim WHERE story_id = ? AND status = 'active'",
        (story_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@dataclass
class EvalReport:
    tier: str | None
    stories: list[StoryScore]
    skipped: list[str] = field(default_factory=list)

    def by_stratum(self) -> dict[str, dict[str, float]]:
        groups: dict[str, list[StoryScore]] = defaultdict(list)
        for s in self.stories:
            groups[s.stratum].append(s)
        out: dict[str, dict[str, float]] = {}
        for k, ss in sorted(groups.items()):
            tp = sum(s.tp for s in ss)
            npred = sum(s.n_preds for s in ss)
            nlab = sum(s.n_labels for s in ss)
            p = tp / npred if npred else 0.0
            r = tp / nlab if nlab else 0.0
            nl = sum(s.numeric_labels for s in ss)
            out[k] = {
                "stories": len(ss),
                "precision": round(p, 3),
                "recall": round(r, 3),
                "f1": round(2 * p * r / (p + r), 3) if (p + r) else 0.0,
                "mean_story_f1": round(sum(s.f1 for s in ss) / len(ss), 3),
                "numeric_error_rate": round(sum(s.numeric_wrong for s in ss) / nl, 3) if nl else 0.0,
            }
        return out

    def render(self) -> str:
        lines = [
            f"eval-extract tier={self.tier or 'db'} stories={len(self.stories)} skipped={len(self.skipped)}"
        ]
        lines.append("| stratum | n | P | R | F1 | mean F1 | numeric err |")
        lines.append("|---|---|---|---|---|---|---|")
        for k, v in self.by_stratum().items():
            lines.append(
                f"| {k} | {v['stories']} | {v['precision']:.2f} | {v['recall']:.2f} | {v['f1']:.2f} | {v['mean_story_f1']:.2f} | {v['numeric_error_rate']:.2f} |"
            )
        for s in self.stories:
            lines.append(
                f"- {s.story_id} [{s.stratum}/{s.lang}] labels={s.n_labels} preds={s.n_preds} tp={s.tp} F1={s.f1:.2f}"
            )
        if self.skipped:
            lines.append(f"skipped (no predictions yet): {', '.join(self.skipped)}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "by_stratum": self.by_stratum(),
            "stories": [
                {
                    "story_id": s.story_id,
                    "stratum": s.stratum,
                    "lang": s.lang,
                    "labels": s.n_labels,
                    "preds": s.n_preds,
                    "tp": s.tp,
                    "f1": round(s.f1, 3),
                    "numeric_labels": s.numeric_labels,
                    "numeric_wrong": s.numeric_wrong,
                }
                for s in self.stories
            ],
            "skipped": self.skipped,
        }


def score(
    conn: sqlite3.Connection,
    *,
    eval_dir: Path = EVAL_DIR,
    tier: str | None = None,
    prompt_version: int | None = None,
    write: bool = True,
) -> EvalReport:
    report = EvalReport(tier=tier, stories=[])
    for label in load_labels(eval_dir):
        preds = predictions(conn, label["story_id"], tier=tier, prompt_version=prompt_version)
        if not preds:
            report.skipped.append(label["story_id"])
            continue
        report.stories.append(score_story(label, preds))
    if write and (report.stories or report.skipped):
        rdir = results_dir(eval_dir)
        rdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        (rdir / f"{stamp}-{tier or 'db'}.json").write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return report


def status(eval_dir: Path = EVAL_DIR) -> dict[str, Any]:
    path = stories_path(eval_dir)
    stories = (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if path.exists()
        else []
    )
    labeled = {d["story_id"] for d in load_labels(eval_dir)}
    by_bucket: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in stories:
        k = f"{s['stratum']}/{s['lang']}"
        by_bucket[k][0] += 1
        by_bucket[k][1] += int(s["story_id"] in labeled)
    return {"stories": len(stories), "labeled": len(labeled), "buckets": dict(by_bucket)}
