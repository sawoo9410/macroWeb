"""Report charts v1 (chart skill conventions, PLAN §8.8/§10.1 chart-maker): one line chart per market series in
the snapshot set (last 60 days), colour by the sign of the latest change, Korean font, caption with source and
as-of date, files charts/<week>/<nn>-<slug>.png and data/weekly/<week>/chart_captions.json. Data only from the
market table; no network."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from macroweb.digest.daily import SNAPSHOT_KEYS
from macroweb.paths import ROOT

CHARTS_DIR = ROOT / "charts"
GREEN, RED, GREY, BLUE = "#2E7D32", "#C62828", "#757575", "#1565C0"
SOURCE_BY_PREFIX = {
    "UST": "미 재무부 par yield",
    "NAVER": "api.stock.naver.com",
    "ECB": "ECB 고시 환율",
    "KRAKEN": "Kraken OHLC",
    "FRED": "FRED",
}
MIN_POINTS = 5


@dataclass
class ChartSpec:
    id: str
    title: str
    key: str
    unit: str
    source: str
    path: Path
    caption: str
    n_points: int
    last_value: float
    last_date: str
    change: float | None = None

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["path"] = str(self.path)
        return d


@dataclass
class ChartsResult:
    week: str
    charts: list[ChartSpec] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    captions_file: Path | None = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _setup_matplotlib():  # type: ignore[no-untyped-def]
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = [
        "Apple SD Gothic Neo",
        "AppleGothic",
        "NanumGothic",
        "Nanum Myeongjo",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def make_week_charts(
    conn: sqlite3.Connection,
    week: str,
    *,
    as_of: str | None = None,
    days: int = 60,
    out_dir: Path | None = None,
    captions_dir: Path | None = None,
    keys: tuple[tuple[str, str, str], ...] = SNAPSHOT_KEYS,
) -> ChartsResult:
    as_of = as_of or datetime.now().date().isoformat()
    since = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
    out = out_dir or (CHARTS_DIR / week)
    out.mkdir(parents=True, exist_ok=True)
    res = ChartsResult(week=week)
    plt = _setup_matplotlib()
    n = 0
    for key, name, unit in keys:
        rows = conn.execute(
            "SELECT date, value FROM market WHERE key = ? AND date >= ? AND date <= ? ORDER BY date",
            (key, since, as_of),
        ).fetchall()
        if len(rows) < MIN_POINTS:
            res.skipped.append(f"{key}: {len(rows)} points (< {MIN_POINTS})")
            continue
        n += 1
        xs = [date.fromisoformat(r["date"]) for r in rows]
        ys = [float(r["value"]) for r in rows]
        change = (ys[-1] - ys[0]) if unit == "%" else (100 * (ys[-1] / ys[0] - 1) if ys[0] else None)
        color = GREY if change is None or abs(change) < 1e-9 else (GREEN if change > 0 else RED)
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=200)
        ax.plot(xs, ys, color=color, linewidth=2)
        ax.scatter([xs[-1]], [ys[-1]], color=BLUE, zorder=3)
        ax.set_title(f"{name} ({key}) — 최근 {len(rows)}일"[:40], fontsize=12)
        ax.set_ylabel({"%": "수익률 (%)", "$": "USD"}.get(unit, "지수/수준"))
        ax.grid(alpha=0.25)
        fig.autofmt_xdate()
        src = SOURCE_BY_PREFIX.get(key.split(":")[0], key.split(":")[0])
        chg_txt = "" if change is None else (f" · 기간 변화 {change:+.2f}{'pp' if unit == '%' else '%'}")
        caption = f"[F] {name} {ys[-1]:,.2f}{'%' if unit == '%' else ''} ({rows[-1]['date']}){chg_txt} · 출처 {src} · 기준일 {as_of}"
        fig.text(0.01, 0.01, caption, fontsize=7, alpha=0.75)
        fig.tight_layout(rect=(0, 0.04, 1, 1))
        path = out / f"{n:02d}-{_slug(name)}.png"
        fig.savefig(path)
        plt.close(fig)
        res.charts.append(
            ChartSpec(
                id=path.stem,
                title=f"{name} ({key})",
                key=key,
                unit=unit,
                source=src,
                path=path,
                caption=caption,
                n_points=len(rows),
                last_value=ys[-1],
                last_date=str(rows[-1]["date"]),
                change=round(change, 4) if change is not None else None,
            )
        )
    cdir = captions_dir or (ROOT / "data" / "weekly" / week)
    cdir.mkdir(parents=True, exist_ok=True)
    res.captions_file = cdir / "chart_captions.json"
    res.captions_file.write_text(
        json.dumps(
            {
                "week": week,
                "as_of": as_of,
                "charts": [c.as_dict() for c in res.charts],
                "skipped": res.skipped,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return res
