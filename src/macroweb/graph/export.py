"""Graph outputs (PLAN §8.8): Obsidian-compatible vault markdown (one node = one file, wikilinks = edges), a
single-file cytoscape.js HTML viewer with an as-of slider and evidence on click, and the weekly ≤ 25-node
subgraph PNG for the report. All content comes from the DB; evidence lists link claim ids to article URLs."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from macroweb.graph.analysis import build_graph, hubs, week_bounds
from macroweb.graph.store import active_edges, entity_rows
from macroweb.paths import ROOT

VAULT_DIR = ROOT / "vault"
CHARTS_DIR = ROOT / "charts"
TYPE_COLORS = {
    "person": "#f4a261",
    "org": "#457b9d",
    "country_bloc": "#8d99ae",
    "policy": "#9d4edd",
    "asset": "#2a9d8f",
    "product_tech": "#e9c46a",
    "event": "#e76f51",
    "theme": "#6a994e",
    "indicator": "#118ab2",
    "scenario": "#adb5bd",
}
SIGN_COLORS = {1: "#2a9d8f", -1: "#e63946", 0: "#999999"}
CYTOSCAPE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.4/cytoscape.min.js"


def _evidence_index(conn: sqlite3.Connection, claim_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not claim_ids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    ids = list(claim_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
            f"""SELECT c.id, c.text, c.label, c.confidence, c.story_id, a.url, a.published_at
                FROM claim c LEFT JOIN evidence e ON e.claim_id = c.id LEFT JOIN article a ON a.id = e.article_id
                WHERE c.id IN ({marks}) GROUP BY c.id""",  # noqa: S608 - placeholders only
            chunk,
        ):
            out[str(r["id"])] = {
                "text": r["text"],
                "label": r["label"],
                "confidence": r["confidence"],
                "url": r["url"],
                "date": (r["published_at"] or "")[:10],
                "story_id": r["story_id"],
            }
    return out


# --- vault -------------------------------------------------------------------------------------------------
@dataclass
class VaultReport:
    entities: int
    index: Path


def export_vault(
    conn: sqlite3.Connection, *, out_dir: Path | None = None, as_of: str | None = None
) -> VaultReport:
    out = out_dir or VAULT_DIR
    edges = active_edges(conn, as_of=as_of)
    ents = entity_rows(conn)
    by_src: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_dst: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for e in edges:
        by_src[e["src_eid"]].append(e)
        by_dst[e["dst_eid"]].append(e)
    claims_by_entity: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for c in conn.execute(
        """SELECT id, text, label, confidence, impact, subject_eid, object_eid, first_seen FROM claim
           WHERE status = 'active' AND (subject_eid IS NOT NULL OR object_eid IS NOT NULL)
           ORDER BY impact DESC, first_seen DESC"""
    ):
        for eid in (c["subject_eid"], c["object_eid"]):
            if eid and len(claims_by_entity[eid]) < 10:
                claims_by_entity[eid].append(c)
    n = 0
    for eid, ent in ents.items():
        etype = ent["type"] or "org"
        d = out / "entities" / etype
        d.mkdir(parents=True, exist_ok=True)
        aliases = json.loads(ent["aliases"] or "[]")
        prof = json.loads(ent["profile_json"] or "{}")
        lines = [
            "---",
            f"id: {eid}",
            f"type: {etype}",
            f"status: {ent['status']}",
            f"aliases: {json.dumps(aliases, ensure_ascii=False)}",
            f"n_stories: {ent['n_stories'] or 0}",
            f"conflict_of_interest: {bool(ent['conflict_of_interest'])}",
            "---",
            f"# {ent['canonical_name'] or eid}",
            "",
        ]
        if ent["conflict_of_interest"]:
            lines.append("> ⚠️ 이해충돌 표시 — 리포트에서는 공시 사실만 쓴다 (CLAUDE.md 데이터 규칙).")
            lines.append("")
        meta = {k: v for k, v in (("country", ent["country"]), ("sector", ent["sector"])) if v}
        meta.update(
            {k: v for k, v in prof.items() if k not in {"card", "seed", "first_story"} and v is not None}
        )
        if meta:
            lines.append("- " + " · ".join(f"{k}: {v}" for k, v in meta.items()))
            lines.append("")
        if prof.get("card"):
            lines.append("## 인물 카드 (시드, ⚠️ evidence 연결 전)")
            lines.append("```yaml")
            lines.append(json.dumps(prof["card"], ensure_ascii=False, indent=1))
            lines.append("```")
            lines.append("")
        lines.append("## 관계 (나가는 엣지)")
        for e in by_src.get(eid, []):
            lines.append(_edge_line(e, "→", e["dst_eid"]))
        lines.append("")
        lines.append("## 관계 (들어오는 엣지)")
        for e in by_dst.get(eid, []):
            lines.append(_edge_line(e, "←", e["src_eid"]))
        lines.append("")
        lines.append("## 주요 claim")
        for c in claims_by_entity.get(eid, []):
            lines.append(f"- `{c['id']}` [{c['label'] or '-'} {float(c['confidence'] or 0):.2f}] {c['text']}")
        lines.append("")
        lines.append(
            f"> 생성: macroweb graph export-vault · {datetime.now(UTC).isoformat(timespec='minutes')}"
        )
        (d / f"{eid}.md").write_text("\n".join(lines), encoding="utf-8")
        n += 1
    index = out / "index.md"
    by_type: dict[str, list[str]] = defaultdict(list)
    for eid, ent in ents.items():
        by_type[ent["type"] or "org"].append(eid)
    idx = [f"# 거미줄 vault — 노드 {n} · 활성 엣지 {len(edges)}", ""]
    for t in sorted(by_type):
        idx.append(f"## {t} ({len(by_type[t])})")
        idx.extend(f"- [[{t}/{eid}|{eid}]]" for eid in sorted(by_type[t]))
        idx.append("")
    index.write_text("\n".join(idx), encoding="utf-8")
    return VaultReport(entities=n, index=index)


def _edge_line(e: sqlite3.Row, arrow: str, other: str) -> str:
    ev = json.loads(e["evidence_ids"] or "[]")
    sign = {1: "+", -1: "−", 0: "0"}[int(e["sign"] or 0)]
    extra = f", r={e['r']} lag={e['lag_days']}d" if e["r"] is not None else ""
    return (
        f"- {e['type']} {arrow} [[{other}]] (sign {sign}, w {float(e['weight'] or 0):.2f} × c {float(e['confidence'] or 0):.2f}, "
        f"evidence {len(ev)}, {e['status']}{extra})"
    )


# --- html --------------------------------------------------------------------------------------------------
def render_html(
    conn: sqlite3.Connection, week: str, *, out_path: Path | None = None, as_of: str | None = None
) -> Path:
    edges = active_edges(conn, as_of=as_of)
    ids = {e["src_eid"] for e in edges} | {e["dst_eid"] for e in edges}
    ents = entity_rows(conn, ids)
    claim_ids = {cid for e in edges for cid in json.loads(e["evidence_ids"] or "[]")}
    evidence = _evidence_index(conn, claim_ids)
    nodes = [
        {
            "data": {
                "id": eid,
                "label": (ents[eid]["canonical_name"] if eid in ents else eid),
                "type": (ents[eid]["type"] if eid in ents else "org"),
                "status": (ents[eid]["status"] if eid in ents else "candidate"),
                "color": TYPE_COLORS.get(ents[eid]["type"] if eid in ents else "org", "#999"),
            }
        }
        for eid in sorted(ids)
    ]
    elems = [
        {
            "data": {
                "id": e["id"],
                "source": e["src_eid"],
                "target": e["dst_eid"],
                "type": e["type"],
                "sign": int(e["sign"] or 0),
                "w": round(float(e["weight"] or 0) * float(e["confidence"] or 0), 3),
                "color": SIGN_COLORS[int(e["sign"] or 0)],
                "valid_from": (e["valid_from"] or "")[:10],
                "status": e["status"],
                "origin": e["origin"],
                "evidence": json.loads(e["evidence_ids"] or "[]"),
            }
        }
        for e in edges
    ]
    dates = sorted({x["data"]["valid_from"] for x in elems if x["data"]["valid_from"]})
    html = _HTML.replace("__WEEK__", week).replace(
        "__ELEMENTS__", json.dumps(nodes + elems, ensure_ascii=False)
    )
    html = html.replace("__EVIDENCE__", json.dumps(evidence, ensure_ascii=False)).replace(
        "__CDN__", CYTOSCAPE_CDN
    )
    html = html.replace("__DATES__", json.dumps(dates)).replace(
        "__GENERATED__", datetime.now(UTC).isoformat(timespec="minutes")
    )
    path = out_path or (CHARTS_DIR / f"graph-{week}.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>거미줄 __WEEK__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#fafafa;--fg:#222;--panel:#fff;--line:#ddd}
@media (prefers-color-scheme: dark){:root{--bg:#121212;--fg:#eee;--panel:#1e1e1e;--line:#333}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 -apple-system,"Apple SD Gothic Neo",sans-serif}
#cy{position:absolute;top:56px;left:0;right:340px;bottom:0}
#side{position:absolute;top:56px;right:0;width:340px;bottom:0;overflow:auto;padding:12px;background:var(--panel);border-left:1px solid var(--line);box-sizing:border-box}
#bar{height:56px;display:flex;gap:12px;align-items:center;padding:0 12px;border-bottom:1px solid var(--line);background:var(--panel)}
#bar input[type=range]{flex:1}
.ev{border-top:1px solid var(--line);padding:6px 0}
.tag{display:inline-block;padding:0 6px;border-radius:4px;font-size:12px;background:#eee;color:#222;margin-right:4px}
small{opacity:.7}
</style></head><body>
<div id="bar"><strong>거미줄 __WEEK__</strong><span>기준일</span><input id="asof" type="range" min="0" max="0" value="0"><span id="asofv">전체</span><small>노드 색=타입 · 엣지 색=부호(초록 이득/빨강 손해/회색 구조) · 굵기=weight×confidence</small></div>
<div id="cy"></div>
<div id="side"><h3>엣지나 노드를 클릭</h3><p><small>생성 __GENERATED__ · 모든 엣지는 evidence(claim) 를 가진다. 시드 엣지는 evidence 0 = 아직 검증 전.</small></p><div id="detail"></div></div>
<script src="__CDN__"></script>
<script>
const ELEMENTS = __ELEMENTS__; const EVIDENCE = __EVIDENCE__; const DATES = __DATES__;
const cy = cytoscape({container: document.getElementById('cy'), elements: ELEMENTS,
  style: [
    {selector: 'node', style: {'background-color': 'data(color)', 'label': 'data(label)', 'font-size': 10, 'width': 18, 'height': 18, 'color': getComputedStyle(document.body).color, 'text-wrap': 'wrap', 'text-max-width': 90}},
    {selector: 'node[status = "candidate"]', style: {'border-width': 2, 'border-style': 'dashed', 'border-color': '#888'}},
    {selector: 'edge', style: {'line-color': 'data(color)', 'target-arrow-color': 'data(color)', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'width': 'mapData(w, 0, 1, 1, 6)', 'opacity': 0.85}},
    {selector: 'edge[origin = "seed"]', style: {'line-style': 'dashed'}},
    {selector: '.hidden', style: {'display': 'none'}},
    {selector: ':selected', style: {'overlay-color': '#ffd166', 'overlay-opacity': 0.35}}
  ],
  layout: {name: 'cose', animate: false, nodeRepulsion: 9000, idealEdgeLength: 90}});
const slider = document.getElementById('asof'); slider.max = DATES.length; slider.value = DATES.length;
function applyAsOf(){ const i = parseInt(slider.value, 10); const cutoff = i >= DATES.length ? null : DATES[i];
  document.getElementById('asofv').textContent = cutoff ? ('≤ ' + cutoff) : '전체';
  cy.edges().forEach(e => { const vf = e.data('valid_from'); const show = !cutoff || !vf || vf <= cutoff; e.toggleClass('hidden', !show); });
  cy.nodes().forEach(n => { n.toggleClass('hidden', n.connectedEdges().not('.hidden').length === 0); }); }
slider.addEventListener('input', applyAsOf);
function esc(s){ return String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
cy.on('tap', 'edge', ev => { const d = ev.target.data(); const el = document.getElementById('detail');
  let h = `<h3>${esc(d.source)} → ${esc(d.target)}</h3><p><span class="tag">${esc(d.type)}</span><span class="tag">sign ${d.sign}</span><span class="tag">w×c ${d.w}</span><span class="tag">${esc(d.status)}</span><span class="tag">${esc(d.origin)}</span><br><small>valid_from ${esc(d.valid_from)}</small></p><h4>evidence (${d.evidence.length})</h4>`;
  if (!d.evidence.length) h += '<p><small>없음 — 시드 엣지. claim 이 붙기 전에는 리포트에 쓰지 않는다.</small></p>';
  d.evidence.forEach(id => { const c = EVIDENCE[id] || {}; h += `<div class="ev"><code>${esc(id)}</code> <span class="tag">${esc(c.label || '-')}</span> ${esc(c.text || '')}<br><small>${esc(c.date || '')} ${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">원문</a>` : ''}</small></div>`; });
  el.innerHTML = h; });
cy.on('tap', 'node', ev => { const n = ev.target; const el = document.getElementById('detail');
  let h = `<h3>${esc(n.data('label'))}</h3><p><span class="tag">${esc(n.data('type'))}</span><span class="tag">${esc(n.data('status'))}</span><code>${esc(n.id())}</code></p><h4>엣지 ${n.connectedEdges().length}</h4>`;
  n.connectedEdges().forEach(e => { const d = e.data(); h += `<div class="ev">${esc(d.source)} —${esc(d.type)}→ ${esc(d.target)} <small>(${d.sign > 0 ? '+' : d.sign < 0 ? '−' : '0'}, ${d.w})</small></div>`; });
  el.innerHTML = h; });
</script></body></html>
"""


# --- png subgraph ------------------------------------------------------------------------------------------
def render_png(
    conn: sqlite3.Connection,
    week: str,
    *,
    out_path: Path | None = None,
    max_nodes: int = 25,
    as_of: str | None = None,
) -> Path | None:
    """This week's web: nodes touched by edges new/reinforced in the week (fallback: strongest hubs), ≤ max_nodes."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    plt.rcParams["font.family"] = [
        "Apple SD Gothic Neo",
        "AppleGothic",
        "NanumGothic",
        "Nanum Myeongjo",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    start, end = week_bounds(week)
    edges = active_edges(conn, as_of=as_of or end[:10])
    if not edges:
        return None
    touched = [e for e in edges if (e["last_reinforced"] or e["valid_from"] or "") >= start]
    g_all = build_graph(edges)
    seed_nodes: list[str] = []
    for e in sorted(touched, key=lambda x: -float(x["weight"] or 0) * float(x["confidence"] or 0)):
        for n in (e["src_eid"], e["dst_eid"]):
            if n not in seed_nodes:
                seed_nodes.append(n)
        if len(seed_nodes) >= max_nodes:
            break
    if len(seed_nodes) < max_nodes:
        for n, _ in hubs(edges, top=max_nodes):
            if n not in seed_nodes:
                seed_nodes.append(n)
            if len(seed_nodes) >= max_nodes:
                break
    sub = g_all.subgraph(seed_nodes[:max_nodes]).copy()
    ents = entity_rows(conn, set(sub.nodes))
    pos = nx.spring_layout(sub, seed=42, k=1.2 / max(1, len(sub) ** 0.5))
    fig, ax = plt.subplots(figsize=(11, 8), dpi=150)
    colors = [TYPE_COLORS.get(ents[n]["type"] if n in ents else "org", "#999") for n in sub.nodes]
    nx.draw_networkx_nodes(
        sub, pos, node_color=colors, node_size=420, alpha=0.95, ax=ax, linewidths=0.5, edgecolors="#333"
    )
    for sign, color in SIGN_COLORS.items():
        es = [(u, v) for u, v, d in sub.edges(data=True) if d["sign"] == sign]
        if es:
            widths = [1 + 4 * sub.edges[u, v]["w"] for u, v in es]
            nx.draw_networkx_edges(
                sub,
                pos,
                edgelist=es,
                edge_color=color,
                width=widths,
                alpha=0.8,
                arrows=True,
                arrowsize=12,
                ax=ax,
            )
    labels = {
        n: (ents[n]["canonical_name"] if n in ents and ents[n]["canonical_name"] else n)[:18]
        for n in sub.nodes
    }
    nx.draw_networkx_labels(sub, pos, labels=labels, font_size=8, ax=ax)
    edge_labels = {(u, v): d["type"] for u, v, d in sub.edges(data=True)}
    nx.draw_networkx_edge_labels(sub, pos, edge_labels=edge_labels, font_size=6, ax=ax, alpha=0.7)
    ax.set_title(
        f"이번 주 거미줄 {week} — 노드 {sub.number_of_nodes()} · 엣지 {sub.number_of_edges()} (초록 이득 / 빨강 손해 / 회색 구조)",
        fontsize=11,
    )
    ax.axis("off")
    fig.text(
        0.01,
        0.01,
        f"출처: macroweb graph (DB), 기준일 {as_of or end[:10]} · 점선 테두리/엣지 = candidate/seed",
        fontsize=7,
        alpha=0.7,
    )
    path = out_path or (CHARTS_DIR / f"graph-{week}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
