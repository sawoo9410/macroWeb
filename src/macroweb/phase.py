"""Phase / Definition-of-Done state (`docs/phase_status.json`). Read by the CLI and by the stdlib-only
Claude Code hooks, so the format is plain JSON (PLAN §14)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from macroweb.paths import PHASE_STATUS


def load() -> dict[str, Any]:
    return json.loads(PHASE_STATUS.read_text(encoding="utf-8"))


def save(state: dict[str, Any]) -> None:
    state["updated"] = date.today().isoformat()
    PHASE_STATUS.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def current_phase(state: dict[str, Any] | None = None) -> str:
    state = state or load()
    return str(state["current_phase"])


def items(state: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    return list(state["phases"][phase]["dod"])


def set_item(phase: str, item_id: str, done: bool) -> dict[str, Any]:
    state = load()
    for item in items(state, phase):
        if item["id"] == item_id:
            item["done"] = done
            item["done_at"] = date.today().isoformat() if done else None
            save(state)
            return item
    raise KeyError(f"no DoD item {item_id!r} in phase {phase}")


def summary_lines(state: dict[str, Any] | None = None) -> list[str]:
    state = state or load()
    phase = current_phase(state)
    dod = items(state, phase)
    done = [i for i in dod if i["done"]]
    todo = [i for i in dod if not i["done"]]
    lines = [f"Phase {phase} ({state['phases'][phase]['name']}): {len(done)}/{len(dod)} DoD done"]
    for i in todo[:5]:
        lines.append(f"  - TODO {i['id']}: {i['text']}")
    if len(todo) > 5:
        lines.append(f"  - ... and {len(todo) - 5} more")
    carry = state.get("carry_over", {})
    for prev_phase, item_ids in carry.items():
        if prev_phase == "note":
            continue
        open_items = [i["id"] for i in items(state, prev_phase) if i["id"] in item_ids and not i["done"]]
        if open_items:
            lines.append(f"  carry-over from Phase {prev_phase}: {', '.join(open_items)}")
    if not todo:
        nxt = str(int(phase) + 1)
        if nxt in state["phases"]:
            lines.append(f"  Phase {phase} complete -> next: Phase {nxt} ({state['phases'][nxt]['name']})")
    return lines
