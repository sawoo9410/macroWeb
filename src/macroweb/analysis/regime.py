"""Regime detector v1 (PLAN §9.2, ADR-0011): six axes judged by rules in config/regime.yaml from the market table
only. Every axis reports its inputs with values and dates, and says "자료 없음" when the series it needs is not
collected yet (FRED liquidity, KRX foreign flows) instead of guessing. Weekly snapshots go to `regime_week` so the
report can flag a regime change against the previous week."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from macroweb.config import CalendarConfig, RegimeConfig, load_regime, load_yaml
from macroweb.paths import CONFIG_DIR

AXES = ("rates", "liquidity", "dollar", "risk", "ai", "kr_flow")
AXIS_LABEL = {
    "rates": "금리",
    "liquidity": "유동성",
    "dollar": "달러",
    "risk": "위험선호",
    "ai": "AI 사이클",
    "kr_flow": "한국 수급",
}
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


@dataclass
class AxisResult:
    axis: str
    state: str | None
    inputs: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"axis": self.axis, "state": self.state, "inputs": self.inputs, "note": self.note}


@dataclass
class RegimeTable:
    as_of: str
    axes: dict[str, AxisResult]
    previous: dict[str, str | None] | None = None
    changed: list[str] = field(default_factory=list)

    def line(self) -> str:
        parts = []
        for a in AXES:
            r = self.axes[a]
            parts.append(f"{AXIS_LABEL[a]} {r.state or '자료 없음'}")
        return " · ".join(parts)

    def alert(self) -> str:
        if not self.previous:
            return "레짐 비교 기준 없음(첫 주)"
        if not self.changed:
            return "레짐 변화 없음(지난주 대비)"
        return "⚠️ 레짐 전환: " + ", ".join(
            f"{AXIS_LABEL[a]} {self.previous.get(a) or '-'} → {self.axes[a].state or '-'}"
            for a in self.changed
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "line": self.line(),
            "alert": self.alert(),
            "axes": {a: r.as_dict() for a, r in self.axes.items()},
            "previous": self.previous,
            "changed": self.changed,
        }


def _point(conn: sqlite3.Connection, key: str, on_or_before: str) -> tuple[str, float] | None:
    r = conn.execute(
        "SELECT date, value FROM market WHERE key = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        (key, on_or_before),
    ).fetchone()
    return (str(r["date"]), float(r["value"])) if r else None


def _change(
    conn: sqlite3.Connection, key: str, as_of: str, window_days: int, *, pct: bool
) -> dict[str, Any] | None:
    """Latest value vs the last value on/before (as_of − window). Returns None when either end is missing."""
    now_pt = _point(conn, key, as_of)
    if now_pt is None:
        return None
    back = (date.fromisoformat(as_of) - timedelta(days=window_days)).isoformat()
    then_pt = _point(conn, key, back)
    out: dict[str, Any] = {"key": key, "value": now_pt[1], "date": now_pt[0]}
    if then_pt is None or then_pt[0] == now_pt[0]:
        out["change"] = None
        out["note"] = f"{window_days}일 전 값 없음 (수집 {now_pt[0]} 부터)"
        return out
    out["from_date"], out["from_value"] = then_pt
    out["change"] = (
        round(100 * (now_pt[1] / then_pt[1] - 1), 2)
        if pct and then_pt[1]
        else round(now_pt[1] - then_pt[1], 4)
    )
    out["change_unit"] = "%" if pct else "pp"
    return out


def next_fomc_hike_market_key(as_of: str) -> str | None:
    """KALSHI:KXFEDDECISION-<YYMON>-H25 for the next confirmed FOMC in config/calendar.yaml."""
    cal = CalendarConfig.model_validate(load_yaml(CONFIG_DIR / "calendar.yaml"))
    today = date.fromisoformat(as_of)
    upcoming = sorted(
        (date.fromisoformat(e.date), e)
        for e in cal.events
        if e.kind == "fomc"
        and e.status == "confirmed"
        and len(e.date) == 10
        and date.fromisoformat(e.date) >= today
    )
    if not upcoming:
        return None
    d = upcoming[0][0]
    return f"KALSHI:KXFEDDECISION-{d.strftime('%y')}{MONTHS[d.month - 1]}-H25"


def compute_regime(
    conn: sqlite3.Connection, *, as_of: str | None = None, cfg: RegimeConfig | None = None
) -> RegimeTable:
    cfg = cfg or load_regime()
    as_of = as_of or datetime.now(UTC).date().isoformat()
    w = cfg.window_days
    axes: dict[str, AxisResult] = {}

    # rates
    th = cfg.axes["rates"].thresholds
    two = _change(conn, "UST:2Y", as_of, w, pct=False)
    ten = _change(conn, "UST:10Y", as_of, w, pct=False)
    r = AxisResult("rates", None, {"UST:2Y": two, "UST:10Y": ten})
    if two and two.get("change") is not None:
        c = float(two["change"])
        r.state = "인상 압력" if c >= th["hike_pp"] else ("인하 기대" if c <= th["cut_pp"] else "동결 구간")
    elif two:
        r.state = "동결 구간(변화 미측정)"
        r.note = str(two.get("note", ""))
    else:
        r.note = "UST:2Y 없음"
    kkey = next_fomc_hike_market_key(as_of)
    if kkey:
        kp = _point(conn, kkey, as_of)
        r.inputs["kalshi_hike_25"] = {
            "key": kkey,
            "prob": kp[1] if kp else None,
            "date": kp[0] if kp else None,
        }
        if kp and kp[1] >= th["kalshi_hike_prob"] and r.state:
            r.state += " · 인상 우세"
    axes["rates"] = r

    # liquidity — needs FRED
    liq = AxisResult("liquidity", None, {}, note="FRED 키 입력 전 (WALCL·RRP·TGA·HY 스프레드 미수집)")
    for key in cfg.axes["liquidity"].inputs:
        pt = _point(conn, key, as_of)
        if pt:
            liq.inputs[key] = {"value": pt[1], "date": pt[0]}
    if liq.inputs:
        liq.note = "FRED 입력 일부 존재 — 규칙은 v2 에서 (현재 판정 안 함)"
    axes["liquidity"] = liq

    # dollar
    th = cfg.axes["dollar"].thresholds
    dxy = _change(conn, "NAVER:.DXY", as_of, w, pct=True)
    krw = _change(conn, "ECB:USD_KRW_CROSS", as_of, w, pct=True)
    d = AxisResult("dollar", None, {"NAVER:.DXY": dxy, "ECB:USD_KRW_CROSS": krw})
    if dxy and dxy.get("change") is not None:
        c = float(dxy["change"])
        d.state = "강" if c >= th["strong_pct"] else ("약" if c <= th["weak_pct"] else "중립")
        if krw and krw.get("change") is not None:
            d.state += f" (원화 {'약세' if krw['change'] > 0 else '강세'} {krw['change']:+.1f}%)"
    elif dxy:
        d.state = "중립(변화 미측정)"
        d.note = str(dxy.get("note", ""))
    else:
        d.note = "DXY 없음"
    axes["dollar"] = d

    # risk
    th = cfg.axes["risk"].thresholds
    vix = _point(conn, "NAVER:.VIX", as_of)
    btc = _change(conn, "KRAKEN:XBTUSD", as_of, w, pct=True)
    k = AxisResult(
        "risk", None, {"NAVER:.VIX": {"value": vix[1], "date": vix[0]} if vix else None, "KRAKEN:XBTUSD": btc}
    )
    if vix:
        k.state = "risk-off" if vix[1] >= th["vix_off"] else ("risk-on" if vix[1] <= th["vix_on"] else "중립")
        if btc and btc.get("change") is not None:
            k.state += f" (BTC {btc['change']:+.1f}%)"
    else:
        k.note = "VIX 없음"
    axes["risk"] = k

    # ai
    th = cfg.axes["ai"].thresholds
    sox = _change(conn, "NAVER:.SOX", as_of, w, pct=True)
    a = AxisResult("ai", None, {"NAVER:.SOX": sox})
    if sox and sox.get("change") is not None:
        c = float(sox["change"])
        a.state = "확장" if c >= th["expand_pct"] else ("조정" if c <= th["correct_pct"] else "정점 논쟁")
    elif sox:
        a.state = "정점 논쟁(변화 미측정)"
        a.note = str(sox.get("note", ""))
    else:
        a.note = "SOX 없음"
    axes["ai"] = a

    # kr_flow
    th = cfg.axes["kr_flow"].thresholds
    kospi = _change(conn, "NAVER:KOSPI", as_of, w, pct=True)
    f = AxisResult(
        "kr_flow",
        None,
        {"NAVER:KOSPI": kospi, "ECB:USD_KRW_CROSS": krw},
        note="KRX 외국인 순매수는 키 입력 후 (가격·환율 대리 지표)",
    )
    if kospi and kospi.get("change") is not None and krw and krw.get("change") is not None:
        kc, wc = float(kospi["change"]), float(krw["change"])
        if kc >= th["kospi_pct"] and wc <= -th["krw_pct"]:
            f.state = "유입(대리)"
        elif kc <= -th["kospi_pct"] and wc >= th["krw_pct"]:
            f.state = "유출(대리)"
        else:
            f.state = "중립"
    elif kospi:
        f.state = "중립(변화 미측정)"
    else:
        f.note = "KOSPI 없음"
    axes["kr_flow"] = f
    return RegimeTable(as_of=as_of, axes=axes)


def _state_core(state: str | None) -> str | None:
    """Drop the parenthetical / suffix detail so week-over-week comparison looks at the regime word only."""
    if not state:
        return None
    return state.split(" (")[0].split(" · ")[0].split("(")[0].strip()


def snapshot_regime(
    conn: sqlite3.Connection, week: str, *, as_of: str | None = None, cfg: RegimeConfig | None = None
) -> RegimeTable:
    """Compute, compare with the latest earlier week in `regime_week`, store this week (upsert)."""
    cfg = cfg or load_regime()
    table = compute_regime(conn, as_of=as_of, cfg=cfg)
    prev = conn.execute(
        "SELECT week, regime_json FROM regime_week WHERE week < ? ORDER BY week DESC LIMIT 1", (week,)
    ).fetchone()
    if prev:
        pj = json.loads(prev["regime_json"] or "{}")
        table.previous = {a: (pj.get("axes", {}).get(a, {}) or {}).get("state") for a in AXES}
        table.previous["week"] = prev["week"]  # type: ignore[assignment]
        if cfg.alert_on_change:
            table.changed = [
                a
                for a in AXES
                if _state_core(table.previous.get(a)) != _state_core(table.axes[a].state)
                and table.axes[a].state
            ]
    conn.execute(
        """INSERT INTO regime_week(week, as_of, regime_json, created_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(week) DO UPDATE SET as_of = excluded.as_of, regime_json = excluded.regime_json, created_at = excluded.created_at""",
        (
            week,
            table.as_of,
            json.dumps(table.as_dict(), ensure_ascii=False),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return table
