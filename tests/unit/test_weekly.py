"""Phase 4 v1: data pack, deterministic gate, publish, and the dry-run weekly runner — no model calls."""

from __future__ import annotations

import json
from pathlib import Path

from test_verify_v1 import NOW, T0_RESULT, T1_RESULT, _collect_fixtures, _story_for

from macroweb.db import repo
from macroweb.extract.persist import persist_result
from macroweb.graph.analysis import iso_week
from macroweb.graph.store import load_seed
from macroweb.llm.schemas import ExtractionResult
from macroweb.publish.weekly import publish_report, strip_portfolio, summary_bits
from macroweb.synth.gate import check_draft
from macroweb.synth.pack import build_pack, write_pack
from macroweb.synth.run_weekly import find_draft, run_weekly, weekly_dir
from macroweb.verify.run import run_verify


def _seed_world(conn, tmp_path: Path):  # type: ignore[no-untyped-def]
    load_seed(conn, now=NOW)
    t0 = _story_for(conn, "fed_press", tier=0, stratum="S-T0-STMT", impact=0.9)
    t1 = _story_for(conn, "yna_economy", tier=1, stratum="S-T1-KO", impact=0.95)
    persist_result(
        conn, t0, ExtractionResult.model_validate(T0_RESULT), extracted_by="test@extract@v2", now=NOW
    )
    persist_result(
        conn, t1, ExtractionResult.model_validate(T1_RESULT), extracted_by="test@extract@v2", now=NOW
    )
    conn.execute(
        "INSERT INTO market(date, key, value, source) VALUES (?, 'NAVER:KOSPI', 2600.9, 'test')",
        ((t1.published_at or "")[:10],),
    )
    conn.commit()
    run_verify(conn, now=NOW, day="2026-11-02", write_md=False)
    return t0, t1


def _draft(verified_id: str, kospi_id: str, *, bad: bool = False) -> str:
    body = f"""# 거미줄 리포트 2026-W45 (2026-11-02 ~ 2026-11-08)

**한 줄:** 연준은 동결, 코스피는 2,600선에서 마감.

## 레짐
금리 동결(매파) · 유동성 중립
데이터 품질: Q1🟢

## 이번 주 거미줄
### 1. 연준 동결
[F] The Committee decided to maintain the target range for the federal funds rate. [{verified_id}]
[F] 코스피가 2,600.5에 마감했다 [{kospi_id}]
[I] 시장은 12월 인상 가능성을 낮게 본다.
{"[F] 코스피가 2,650에 마감했다 [" + kospi_id + "]" if bad else ""}
{"지금 반도체를 매수하라." if bad else ""}

## 검증 노트 — 이번 주 걸러낸 것
- 없음

## 논제 보드
| # | 논제 | 기간 | 확률 | 틀리면 |
|---|---|---|---|---|
| 1 | 12월 FOMC 동결 | 2026-12-09 | 0.6 | 점도표 상향 |
| 2 | 코스피 외국인 순매도 지속 | 2주 | 0.5 | 순매수 전환 |

## (비공개) 내 포트폴리오에 걸린 엣지
{"삼성전자 100주, 1,000만원" if bad else "반도체 비중이 큰 편 — 금리 경로에 민감."}

## 부록
- 출처: pack.json
"""
    return body


def test_pack_gate_publish_and_dry_run(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MACROWEB_REVIEW_DIR", str(tmp_path / "review"))
    _collect_fixtures()
    conn = repo.connect()
    try:
        t0, t1 = _seed_world(conn, tmp_path)
        week = iso_week(NOW.date())
        pack = build_pack(conn, week, now=NOW)
        assert pack["week"] == week and pack["claims"], "verified claims from this week must be in the pack"
        labels = {c["label"] for c in pack["claims"]}
        assert labels <= {"VERIFIED", "CORROBORATED"}
        assert pack["quality"]["note"]  # no quality run yet → said explicitly, not invented
        assert "market" in pack and "calendar_14d" in pack and pack["graph"]["diff"]["new_edges"] >= 17
        assert set(pack["slices"]) == {"macro", "policy", "semis", "korea", "cartographer", "historian"}
        paths = write_pack(conn, week, now=NOW)
        assert paths.pack.exists() and (paths.pack.parent / "slices" / "korea.json").exists()
        korea = json.loads((paths.pack.parent / "slices" / "korea.json").read_text(encoding="utf-8"))
        assert all(c["lang"] == "ko" or c["theme"] == "korea-foreign-flows" for c in korea["claims"])

        verified = conn.execute("SELECT id FROM claim WHERE text LIKE 'The Committee decided%'").fetchone()[
            "id"
        ]
        kospi = conn.execute("SELECT id FROM claim WHERE text = '코스피가 2,600.5에 마감했다'").fetchone()[
            "id"
        ]
        good = check_draft(conn, _draft(verified, kospi))
        assert good.passed and good.n_fact_sentences == 2 and good.n_checked_numbers == 1, good.render()
        bad = check_draft(conn, _draft(verified, kospi, bad=True))
        rules = {v.rule for v in bad.violations}
        assert not bad.passed and {"number_mismatch", "forbidden_phrase", "portfolio_amount"} <= rules, (
            bad.render()
        )
        unknown = check_draft(conn, "[F] something [0123456789abcdef]\n[F] no citation here\n")
        assert {v.rule for v in unknown.violations} == {"unknown_claim_id", "fact_without_claim_id"}
        weak = conn.execute("SELECT id FROM claim WHERE label = 'UNVERIFIABLE'").fetchone()["id"]
        assert any(v.rule == "label_too_weak_for_F" for v in check_draft(conn, f"[F] x [{weak}]").violations)

        # publish into temp dirs
        draft = weekly_dir(week) / "draft.md"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(_draft(verified, kospi), encoding="utf-8")
        dirs = {
            "reports_dir": tmp_path / "reports",
            "drafts_dir": tmp_path / "drafts",
            "vault_dir": tmp_path / "vault",
        }
        res = publish_report(conn, week, draft, notify=False, **dirs)
        assert res.report.exists() and res.blog.exists() and res.vault_note.exists()
        assert res.one_liner.startswith("연준은 동결") and len(res.theses) == 2 and res.citations == 2
        assert "(비공개)" not in res.blog.read_text(encoding="utf-8") and "(비공개)" in res.report.read_text(
            encoding="utf-8"
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM report_citation WHERE report_week = ?", (week,)).fetchone()[0]
            == 2
        )
        assert strip_portfolio("## a\nx\n## (비공개) p\nsecret\n## b\ny\n") == "## a\nx\n## b\ny\n"
        assert summary_bits(
            "**한 줄:** hi\n## 논제 보드\n| # | 논제 |\n|---|---|\n| 1 | T1 |\n## 다음\n"
        ) == ("hi", ["T1"])

        # dry-run runner: quality → pack → gate on the existing draft → publish (temp dirs), run row recorded
        rep = run_weekly(week, dry_run=True, conn=conn, publish_dirs=dirs, notify=False)
        assert rep.quality_line and rep.quality_line.startswith("데이터 품질:")
        assert rep.pack_path and rep.gate and rep.gate.passed and rep.published and not rep.stopped, (
            rep.render()
        )
        assert (
            find_draft(week) == draft
            and (weekly_dir(week) / "gate.json").exists()
            and (weekly_dir(week) / "steps.jsonl").exists()
        )
        run_row = conn.execute(
            "SELECT status, stats_json FROM run WHERE job = 'weekly' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        assert run_row["status"] == "ok" and json.loads(run_row["stats_json"])["gate"]["pass"] is True
        # without a draft the runner stops cleanly and says so
        draft.unlink()
        rep2 = run_weekly(week, dry_run=True, conn=conn, publish_dirs=dirs, notify=False, skip_quality=True)
        assert rep2.stopped and "no draft" in rep2.stopped and rep2.published is None
    finally:
        conn.close()
