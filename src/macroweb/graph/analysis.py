"""Graph analysis v1 (PLAN §8.6–8.7): shock propagation, k-shortest explanation paths, weighted PageRank hubs,
weekly diff/snapshot, and the statistical-edge calculator (r/lag from the market table — computed, never
estimated). Pure functions over the relation rows that `graph.store.active_edges` returns."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import networkx as nx

from macroweb.graph.store import active_edges, graph_counts

IMPACT_EDGES = {
    "benefits_from",
    "hurt_by",
    "depends_on",
    "exposed_to",
    "triggers",
    "correlates_with",
    "supplies_to",
    "customer_of",
    "pressures",
}
DECAY = {1: 1.0, 2: 0.6, 3: 0.35}


def build_graph(edges: list[sqlite3.Row]) -> nx.DiGraph:
    g = nx.DiGraph()
    for e in edges:
        w = float(e["weight"] or 0) * float(e["confidence"] or 0)
        key = (e["src_eid"], e["dst_eid"])
        if g.has_edge(*key) and g.edges[key]["w"] >= w:
            g.edges[key]["types"].append(e["type"])
            continue
        g.add_edge(
            e["src_eid"],
            e["dst_eid"],
            w=w,
            sign=int(e["sign"] or 0),
            type=e["type"],
            types=[e["type"]],
            rid=e["id"],
            evidence=e["evidence_ids"],
        )
    return g


@dataclass
class Effect:
    target: str
    sign: int
    magnitude: float
    depth: int
    path: list[str]  # relation ids
    nodes: list[str]
    evidence: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "sign": self.sign,
            "magnitude": round(self.magnitude, 4),
            "depth": self.depth,
            "path": self.path,
            "nodes": self.nodes,
            "evidence": self.evidence,
        }


def propagate(
    edges: list[sqlite3.Row],
    shock: str,
    *,
    sign: int = 1,
    magnitude: float = 1.0,
    max_depth: int = 3,
    floor: float = 0.05,
) -> list[Effect]:
    """PLAN §8.7 verbatim: follow impact edges, multiply sign, decay by depth, stop below the floor.
    Effects on the same target are kept separately (different paths = different explanations)."""
    out_edges: dict[str, list[sqlite3.Row]] = {}
    for e in edges:
        if e["type"] in IMPACT_EDGES:
            out_edges.setdefault(e["src_eid"], []).append(e)
    frontier: list[tuple[str, int, float, list[str], list[str], list[str]]] = [
        (shock, sign, magnitude, [], [shock], [])
    ]
    effects: list[Effect] = []
    for depth in range(1, max_depth + 1):
        nxt = []
        for node, s, m, path, nodes, ev in frontier:
            for e in out_edges.get(node, []):
                if e["dst_eid"] in nodes:
                    continue  # no cycles
                s2 = s * int(e["sign"] or 0)
                m2 = m * float(e["weight"] or 0) * float(e["confidence"] or 0) * DECAY.get(depth, 0.2)
                if m2 < floor:
                    continue
                ev2 = ev + json.loads(e["evidence_ids"] or "[]")
                eff = Effect(e["dst_eid"], s2, m2, depth, path + [e["id"]], nodes + [e["dst_eid"]], ev2)
                effects.append(eff)
                nxt.append((e["dst_eid"], s2, m2, path + [e["id"]], nodes + [e["dst_eid"]], ev2))
        frontier = nxt
    effects.sort(key=lambda x: (-x.magnitude, x.depth))
    return effects


def k_paths(
    edges: list[sqlite3.Row], src: str, dst: str, *, k: int = 3, max_len: int = 5
) -> list[dict[str, Any]]:
    """k best simple paths by (hops, −product of weight×confidence). Explains "how does X reach Y"."""
    g = build_graph(edges)
    if src not in g or dst not in g:
        return []
    found: list[dict[str, Any]] = []
    for nodes in nx.all_simple_paths(g, src, dst, cutoff=max_len):
        score = 1.0
        rids, signs = [], 1
        for a, b in zip(nodes, nodes[1:], strict=False):
            d = g.edges[a, b]
            score *= max(d["w"], 1e-6)
            rids.append(d["rid"])
            signs *= d["sign"] if d["sign"] else 1
        found.append(
            {
                "nodes": nodes,
                "edges": rids,
                "strength": round(score, 4),
                "net_sign": signs,
                "hops": len(nodes) - 1,
            }
        )
        if len(found) > 500:
            break
    found.sort(key=lambda p: (p["hops"], -p["strength"]))
    return found[:k]


def pagerank(
    g: nx.DiGraph, *, damping: float = 0.85, iters: int = 100, tol: float = 1e-8
) -> dict[str, float]:
    """Weighted PageRank by power iteration (pure Python — networkx's version needs scipy)."""
    nodes = list(g.nodes)
    n = len(nodes)
    if n == 0:
        return {}
    rank = dict.fromkeys(nodes, 1.0 / n)
    out_w = {u: sum(float(d.get("w", 0) or 0) for _, _, d in g.out_edges(u, data=True)) for u in nodes}
    for _ in range(iters):
        nxt = dict.fromkeys(nodes, (1 - damping) / n)
        dangling = sum(rank[u] for u in nodes if out_w[u] <= 0)
        for u in nodes:
            nxt[u] += damping * dangling / n
        for u, v, d in g.edges(data=True):
            if out_w[u] > 0:
                nxt[v] += damping * rank[u] * float(d.get("w", 0) or 0) / out_w[u]
        delta = sum(abs(nxt[u] - rank[u]) for u in nodes)
        rank = nxt
        if delta < tol:
            break
    return rank


def hubs(edges: list[sqlite3.Row], *, top: int = 10) -> list[tuple[str, float]]:
    g = build_graph(edges)
    if g.number_of_nodes() == 0:
        return []
    return sorted(pagerank(g).items(), key=lambda kv: -kv[1])[:top]


# --- weekly diff / snapshot -------------------------------------------------------------------------------
def week_bounds(week: str) -> tuple[str, str]:
    """ISO week 'YYYY-Www' → [Monday 00:00 UTC, next Monday) as ISO strings."""
    year, wk = week.split("-W")
    monday = date.fromisocalendar(int(year), int(wk), 1)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=UTC)
    return start.isoformat(timespec="seconds"), (start + timedelta(days=7)).isoformat(timespec="seconds")


def iso_week(d: date | None = None) -> str:
    y, w, _ = (d or datetime.now(UTC).date()).isocalendar()
    return f"{y}-W{w:02d}"


@dataclass
class WeekDiff:
    week: str
    new_edges: list[sqlite3.Row] = field(default_factory=list)
    reinforced: list[sqlite3.Row] = field(default_factory=list)
    expired: list[sqlite3.Row] = field(default_factory=list)
    new_entities: list[sqlite3.Row] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    previous: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "new_edges": len(self.new_edges),
            "reinforced": len(self.reinforced),
            "expired": len(self.expired),
            "new_entities": len(self.new_entities),
            **self.counts,
            "previous": self.previous,
        }


def weekly_diff(conn: sqlite3.Connection, week: str, *, snapshot: bool = True) -> WeekDiff:
    start, end = week_bounds(week)
    d = WeekDiff(week=week)
    d.new_edges = conn.execute(
        "SELECT * FROM relation WHERE valid_from >= ? AND valid_from < ? AND status IN ('candidate','confirmed') ORDER BY weight*confidence DESC",
        (start, end),
    ).fetchall()
    d.reinforced = conn.execute(
        "SELECT * FROM relation WHERE last_reinforced >= ? AND last_reinforced < ? AND valid_from < ? AND status IN ('candidate','confirmed')",
        (start, end, start),
    ).fetchall()
    d.expired = conn.execute(
        "SELECT * FROM relation WHERE valid_to >= ? AND valid_to < ?", (start, end)
    ).fetchall()
    d.new_entities = conn.execute(
        "SELECT * FROM entity WHERE valid_from >= ? AND valid_from < ? AND status != 'merged'",
        (start[:10], end[:10]),
    ).fetchall()
    d.counts = graph_counts(conn)
    prev = conn.execute(
        "SELECT week, n_nodes, n_edges, stats_json FROM graph_snapshot WHERE week < ? ORDER BY week DESC LIMIT 1",
        (week,),
    ).fetchone()
    if prev:
        d.previous = {"week": prev["week"], "n_nodes": prev["n_nodes"], "n_edges": prev["n_edges"]}
    if snapshot:
        edges = active_edges(conn, as_of=end[:10])
        nodes = {e["src_eid"] for e in edges} | {e["dst_eid"] for e in edges}
        conn.execute(
            """INSERT INTO graph_snapshot(week, taken_at, as_of, n_nodes, n_edges, edge_ids_json, stats_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(week) DO UPDATE SET taken_at = excluded.taken_at, as_of = excluded.as_of, n_nodes = excluded.n_nodes,
                 n_edges = excluded.n_edges, edge_ids_json = excluded.edge_ids_json, stats_json = excluded.stats_json""",
            (
                week,
                datetime.now(UTC).isoformat(timespec="seconds"),
                end[:10],
                len(nodes),
                len(edges),
                json.dumps([e["id"] for e in edges]),
                json.dumps(d.summary(), ensure_ascii=False),
            ),
        )
        conn.commit()
    return d


# --- statistical edges -------------------------------------------------------------------------------------
@dataclass
class PairStats:
    key_a: str
    key_b: str
    n: int
    r: float | None = None
    lag_days: int | None = None
    note: str = ""
    by_lag: dict[int, float] = field(default_factory=dict)


def _series(conn: sqlite3.Connection, key: str, days: int) -> dict[date, float]:
    since = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    return {
        date.fromisoformat(r["date"]): float(r["value"])
        for r in conn.execute(
            "SELECT date, value FROM market WHERE key = ? AND date >= ? ORDER BY date", (key, since)
        )
    }


def _changes(series: dict[date, float], *, log_returns: bool) -> dict[date, float]:
    days = sorted(series)
    out: dict[date, float] = {}
    for a, b in zip(days, days[1:], strict=False):
        va, vb = series[a], series[b]
        if log_returns:
            if va > 0 and vb > 0:
                out[b] = math.log(vb / va)
        else:
            out[b] = vb - va
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / math.sqrt(sxx * syy)


def pair_stats(
    conn: sqlite3.Connection,
    key_a: str,
    key_b: str,
    *,
    days: int = 730,
    lags: range = range(-5, 31),
    min_points: int = 60,
    min_abs_r: float = 0.3,
    yield_keys: tuple[str, ...] = ("UST:",),
) -> PairStats:
    """r and lag (days by which `a` leads `b`) on daily changes: log-returns for prices, differences for yields.
    Needs ≥ min_points overlapping observations; otherwise reports 'insufficient history' with r = None."""
    sa = _changes(_series(conn, key_a, days), log_returns=not key_a.startswith(yield_keys))
    sb = _changes(_series(conn, key_b, days), log_returns=not key_b.startswith(yield_keys))
    ps = PairStats(key_a, key_b, n=0)
    if not sa or not sb:
        ps.note = "no market data for one of the keys"
        return ps
    best: tuple[float, int, int] | None = None
    for lag in lags:
        xs, ys = [], []
        for d, x in sa.items():
            y = sb.get(d + timedelta(days=lag))
            if y is not None:
                xs.append(x)
                ys.append(y)
        if len(xs) < min_points:
            continue
        r = pearson(xs, ys)
        if r is None:
            continue
        ps.by_lag[lag] = round(r, 4)
        if best is None or abs(r) > abs(best[0]):
            best = (r, lag, len(xs))
    if best is None:
        ps.n = max((len(set(sa) & {d - timedelta(days=lag) for d in sb}) for lag in lags), default=0)
        ps.note = f"insufficient history (need {min_points} overlapping daily changes)"
        return ps
    ps.r, ps.lag_days, ps.n = round(best[0], 4), best[1], best[2]
    if abs(best[0]) < min_abs_r:
        ps.note = f"|r| < {min_abs_r}: no edge"
    return ps
