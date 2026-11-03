"""Phase 5 v1: regime detector rules on a synthetic market series (test double), cross-asset consistency against
seed edges, thesis ledger with auto-scoring, and report charts. No model calls, no network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from macroweb.analysis.consistency import cross_asset_check
from macroweb.analysis.regime import compute_regime, next_fomc_hike_market_key, snapshot_regime
from macroweb.analysis.thesis import (
    add_thesis,
    auto_score,
    board_rows,
    calibration,
    list_theses,
    score_thesis,
)
from macroweb.db import repo
from macroweb.graph.store import load_seed
from macroweb.publish.charts import make_week_charts

AS_OF = date(2026, 11, 2)


def _series(conn, key: str, start: float, step: float, days: int = 40, end: date = AS_OF) -> None:  # type: ignore[no-untyped-def]
    """Linear daily series ending at `end` — a test double for the market table."""
    rows = [
        ((end - timedelta(days=days - 1 - i)).isoformat(), key, start + step * i, "test") for i in range(days)
    ]
    conn.executemany("INSERT OR REPLACE INTO market(date, key, value, source) VALUES (?, ?, ?, ?)", rows)
    conn.commit()


def test_regime_rules_and_data_gaps() -> None:
    repo.init_db()
    conn = repo.connect()
    try:
        empty = compute_regime(conn, as_of=AS_OF.isoformat())
        assert all(r.state is None for r in empty.axes.values()) and "자료 없음" in empty.line()
        _series(conn, "UST:2Y", 4.00, 0.01)  # +0.39pp over 40 days → 인상 압력
        _series(conn, "UST:10Y", 4.50, 0.005)
        _series(conn, "NAVER:.DXY", 100.0, -0.06)  # −2.3% → 약
        _series(conn, "ECB:USD_KRW_CROSS", 1400.0, -1.0)  # 원화 강세
        _series(conn, "NAVER:.VIX", 30.0, 0.0)  # risk-off
        _series(conn, "NAVER:.SOX", 5000.0, -15.0)  # −10.6% → 조정
        _series(conn, "NAVER:KOSPI", 2500.0, 2.0)  # +3% with KRW stronger → 유입(대리)
        key = next_fomc_hike_market_key(AS_OF.isoformat())
        assert key == "KALSHI:KXFEDDECISION-26DEC-H25"
        conn.execute(
            "INSERT INTO market(date, key, value, source) VALUES (?, ?, 0.62, 'test')",
            (AS_OF.isoformat(), key),
        )
        conn.commit()
        t = compute_regime(conn, as_of=AS_OF.isoformat())
        assert t.axes["rates"].state == "인상 압력 · 인상 우세"
        assert t.axes["dollar"].state.startswith("약") and "원화 강세" in t.axes["dollar"].state
        assert t.axes["risk"].state.startswith("risk-off") and t.axes["ai"].state == "조정"
        assert t.axes["kr_flow"].state == "유입(대리)" and t.axes["liquidity"].state is None
        assert t.axes["rates"].inputs["UST:2Y"]["change"] == pytest.approx(0.28, abs=0.02)
        line = t.line()
        assert "금리 인상 압력" in line and "유동성 자료 없음" in line
        # weekly snapshot + change alert against a stored previous week
        first = snapshot_regime(conn, "2026-W44", as_of=AS_OF.isoformat())
        assert first.previous is None and "첫 주" in first.alert()
        conn.execute("UPDATE market SET value = 12 WHERE key = 'NAVER:.VIX'")
        conn.commit()
        second = snapshot_regime(conn, "2026-W45", as_of=AS_OF.isoformat())
        assert (
            second.changed == ["risk"]
            and "레짐 전환" in second.alert()
            and second.previous["week"] == "2026-W44"
        )
        assert conn.execute("SELECT COUNT(*) FROM regime_week").fetchone()[0] == 2
    finally:
        conn.close()


def test_cross_asset_consistency_with_seed_edges() -> None:
    repo.init_db()
    conn = repo.connect()
    try:
        load_seed(conn, now=datetime(2026, 10, 1, tzinfo=UTC))  # seed edges must be valid as of AS_OF
        _series(conn, "UST:10Y", 4.00, 0.02, days=10)  # rising 10Y confirms "FOMC +→ UST10Y +"
        _series(conn, "NAVER:.SOX", 5000.0, 30.0, days=10)  # SOX rising contradicts "UST10Y −→ SOX"
        rep = cross_asset_check(conn, [("fomc-2026-12-09", 1)], as_of=AS_OF.isoformat(), floor=0.01)
        by = {c.target: c for c in rep.checks}
        assert by["ust10y"].verdict == "confirms" and by["ust10y"].unit == "pp"
        assert by["sox"].verdict == "contradicts" and by["sox"].predicted_sign == -1
        assert "불일치 1" in rep.line() and rep.contradictions[0].target == "sox"
        assert cross_asset_check(conn, [("nonexistent", 1)], as_of=AS_OF.isoformat()).checks == []
    finally:
        conn.close()


def test_thesis_ledger_auto_and_human_scoring() -> None:
    repo.init_db()
    conn = repo.connect()
    try:
        _series(conn, "UST:2Y", 4.0, 0.01, days=10)
        t = add_thesis(
            conn,
            week="2026-W44",
            text="2026-11-01까지 미 2Y 가 4.05% 이상일 확률 0.7. 틀렸다면 고용 급랭이 먼저 보인다.",
            horizon_date="2026-11-01",
            probability=0.7,
            falsifier="고용 급랭",
            claim_ids=["abc"],
            auto={"market_key": "UST:2Y", "op": ">=", "threshold": 4.05},
        )
        assert t.status == "open" and t.id.startswith("th-")
        assert (
            add_thesis(conn, week="2026-W44", text=t.text, horizon_date="2026-11-01", probability=0.6).id
            == t.id
        )  # idempotent
        human = add_thesis(
            conn,
            week="2026-W44",
            text="2026-11-01까지 사람 판단 논제",
            horizon_date="2026-11-01",
            probability=0.4,
        )
        future = add_thesis(
            conn, week="2026-W44", text="2027-01-01까지 미래 논제", horizon_date="2027-01-01", probability=0.5
        )
        res = auto_score(conn, today=AS_OF)
        assert res["scored"] == [t.id] and res["due"] == [human.id]
        scored = list_theses(conn, week="2026-W44", status="scored_auto")[0]
        assert scored.outcome == 1 and scored.brier == pytest.approx((0.6 - 1) ** 2)
        h = score_thesis(conn, human.id, 0)
        assert h.status == "scored_human" and h.brier == pytest.approx(0.16)
        assert list_theses(conn, status="open") == [future] or [
            x.id for x in list_theses(conn, status="open")
        ] == [future.id]
        cal = calibration(conn)
        assert cal["n"] == 2 and cal["mean_brier"] == pytest.approx((0.16 + 0.16) / 2)
        assert board_rows([future]).startswith("| 1 | 2027-01-01까지 미래 논제 | 2027-01-01 | 0.50 |")
        with pytest.raises(ValueError):
            add_thesis(conn, week="w", text="x", horizon_date="2026-01-01", probability=1.5)
    finally:
        conn.close()


def test_week_charts_from_market_table(tmp_path: Path) -> None:
    repo.init_db()
    conn = repo.connect()
    try:
        _series(conn, "UST:10Y", 4.0, 0.01, days=20)
        _series(conn, "NAVER:KOSPI", 2500.0, -3.0, days=20)
        conn.execute(
            "INSERT INTO market(date, key, value, source) VALUES (?, 'NAVER:.VIX', 20, 'test')",
            (AS_OF.isoformat(),),
        )
        conn.commit()
        res = make_week_charts(
            conn,
            "2026-W45",
            as_of=AS_OF.isoformat(),
            out_dir=tmp_path / "charts",
            captions_dir=tmp_path / "weekly",
        )
        names = [c.key for c in res.charts]
        assert names == ["UST:10Y", "NAVER:KOSPI"] and any("NAVER:.VIX" in s for s in res.skipped)
        assert all(c.path.exists() and c.path.stat().st_size > 1000 for c in res.charts)
        assert res.charts[0].caption.startswith("[F]") and "기준일 2026-11-02" in res.charts[0].caption
        caps = json.loads(res.captions_file.read_text(encoding="utf-8"))
        assert caps["week"] == "2026-W45" and len(caps["charts"]) == 2 and caps["charts"][1]["change"] < 0
    finally:
        conn.close()
