"""Cross-asset consistency check v1 (PLAN §8.7 last paragraph, §9.4): compare what the graph's propagation
*predicts* for assets with what prices actually did. A mismatch is not an error — it is the week's best
insight candidate ("the market sees it differently") and a mandatory input for the chief editor."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from macroweb.graph.analysis import propagate
from macroweb.graph.store import active_edges, entity_rows

MIN_MOVE_PCT = 0.5  # below this the market "did nothing" — neither confirms nor contradicts


@dataclass
class Mismatch:
    shock: str
    target: str
    data_key: str
    predicted_sign: int
    actual_change: float
    unit: str
    window: str
    path: list[str]
    verdict: str  # confirms | contradicts | flat

    def as_dict(self) -> dict[str, Any]:
        return {
            "shock": self.shock,
            "target": self.target,
            "data_key": self.data_key,
            "predicted_sign": self.predicted_sign,
            "actual_change": self.actual_change,
            "unit": self.unit,
            "window": self.window,
            "path": self.path,
            "verdict": self.verdict,
        }


@dataclass
class ConsistencyReport:
    as_of: str
    checks: list[Mismatch] = field(default_factory=list)
    note: str = ""

    @property
    def contradictions(self) -> list[Mismatch]:
        return [c for c in self.checks if c.verdict == "contradicts"]

    def line(self) -> str:
        if not self.checks:
            return self.note or "비교할 전파 예측·가격 쌍 없음"
        n_ok = sum(1 for c in self.checks if c.verdict == "confirms")
        n_bad = len(self.contradictions)
        n_flat = len(self.checks) - n_ok - n_bad
        bits = [f"확인 {n_ok} · 불일치 {n_bad} · 무반응 {n_flat}"]
        for c in self.contradictions[:3]:
            bits.append(
                f"{c.shock}→{c.target} 예측 {'+' if c.predicted_sign > 0 else '−'} vs 실제 {c.actual_change:+.2f}{c.unit}"
            )
        return " / ".join(bits)

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "line": self.line(),
            "checks": [c.as_dict() for c in self.checks],
            "note": self.note,
        }


def _price_change(conn: sqlite3.Connection, key: str, as_of: str, days: int) -> tuple[float, str] | None:
    now = conn.execute(
        "SELECT date, value FROM market WHERE key = ? AND date <= ? ORDER BY date DESC LIMIT 1", (key, as_of)
    ).fetchone()
    if not now:
        return None
    back = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    then = conn.execute(
        "SELECT date, value FROM market WHERE key = ? AND date <= ? ORDER BY date DESC LIMIT 1", (key, back)
    ).fetchone()
    if not then or then["date"] == now["date"]:
        return None
    if key.startswith("UST:"):
        return round(float(now["value"]) - float(then["value"]), 4), "pp"
    if float(then["value"]) == 0:
        return None
    return round(100 * (float(now["value"]) / float(then["value"]) - 1), 2), "%"


def cross_asset_check(
    conn: sqlite3.Connection,
    shocks: list[tuple[str, int]],
    *,
    as_of: str | None = None,
    window_days: int = 7,
    floor: float = 0.02,
) -> ConsistencyReport:
    """For each (shock node, sign): propagate, keep effects on asset nodes with a `data_key`, compare the
    predicted sign with the realised change over `window_days` ending at `as_of`."""
    as_of = as_of or datetime.now().date().isoformat()
    rep = ConsistencyReport(as_of=as_of)
    edges = active_edges(conn, as_of=as_of)
    if not edges:
        rep.note = "활성 엣지 없음"
        return rep
    ents = entity_rows(conn)
    data_keys = {}
    for eid, row in ents.items():
        try:
            dk = json.loads(row["profile_json"] or "{}").get("data_key")
        except json.JSONDecodeError:
            dk = None
        if dk:
            data_keys[eid] = str(dk)
    seen: set[tuple[str, str]] = set()
    for shock, sign in shocks:
        for eff in propagate(edges, shock, sign=sign, magnitude=1.0, floor=floor):
            key = data_keys.get(eff.target)
            if not key or (shock, eff.target) in seen:
                continue
            seen.add((shock, eff.target))
            chg = _price_change(conn, key, as_of, window_days)
            if chg is None:
                continue
            actual, unit = chg
            if abs(actual) < (0.05 if unit == "pp" else MIN_MOVE_PCT):
                verdict = "flat"
            elif (actual > 0) == (eff.sign > 0):
                verdict = "confirms"
            else:
                verdict = "contradicts"
            rep.checks.append(
                Mismatch(
                    shock,
                    eff.target,
                    key,
                    eff.sign,
                    actual,
                    unit,
                    f"{window_days}d to {as_of}",
                    eff.nodes,
                    verdict,
                )
            )
    if not rep.checks:
        rep.note = "전파 대상 자산에 가격 창(7일) 데이터가 아직 부족"
    return rep
