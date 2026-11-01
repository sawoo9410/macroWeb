"""Connection, schema bootstrap, migrations, integrity checks and the `run` ledger."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from macroweb.paths import db_path

SCHEMA_SQL = Path(__file__).with_name("schema.sql")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.__fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def trigram_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__tri_probe USING fts5(x, tokenize='trigram')")
        conn.execute("DROP TABLE temp.__tri_probe")
        return True
    except sqlite3.OperationalError:
        return False


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["v"] or 0)


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return sorted(r["name"] for r in rows)


def _pending_migrations(current: int) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"^(\d{4})_", p.name)
        if m and int(m.group(1)) > current:
            out.append((int(m.group(1)), p))
    return out


def init_db(path: Path | None = None) -> dict[str, Any]:
    """Idempotent: creates schema v1 when the DB is empty, then applies pending migrations."""
    conn = connect(path)
    try:
        created = False
        notes: list[str] = []
        if schema_version(conn) == 0:
            if not fts5_available(conn):
                raise RuntimeError("SQLite build lacks FTS5; cannot create article_fts")
            sql = SCHEMA_SQL.read_text(encoding="utf-8")
            if not trigram_available(conn):
                sql = sql.replace("tokenize='trigram'", "tokenize='unicode61'")
                notes.append("trigram tokenizer unavailable -> unicode61 (Korean FTS quality degraded)")
            conn.executescript(sql)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version(version, applied_at, note) VALUES (?, ?, ?)",
                (SCHEMA_VERSION, _now(), "; ".join(notes) or "schema v1"),
            )
            conn.commit()
            created = True
        applied: list[str] = []
        for version, p in _pending_migrations(schema_version(conn)):
            conn.executescript(p.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_version(version, applied_at, note) VALUES (?, ?, ?)",
                (version, _now(), p.name),
            )
            conn.commit()
            applied.append(p.name)
        return {
            "path": str(path or db_path()),
            "created": created,
            "schema_version": schema_version(conn),
            "applied_migrations": applied,
            "tables": table_names(conn),
            "notes": notes,
        }
    finally:
        conn.close()


def integrity_check(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


# --- run ledger (PLAN §13.6) ------------------------------------------------------------------------
def start_run(conn: sqlite3.Connection, job: str, prompt_versions: dict[str, str] | None = None) -> str:
    run_id = f"{job}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO run(id, job, started_at, status, prompt_versions) VALUES (?, ?, ?, 'running', ?)",
        (run_id, job, _now(), json.dumps(prompt_versions or {}, ensure_ascii=False)),
    )
    conn.commit()
    return run_id


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    stats: dict[str, Any] | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    model_tier: str | None = None,
    cost_usd: float = 0.0,
) -> None:
    conn.execute(
        "UPDATE run SET ended_at=?, status=?, stats_json=?, tokens_in=?, tokens_out=?, model_tier=?, cost_usd=? WHERE id=?",
        (
            _now(),
            status,
            json.dumps(stats or {}, ensure_ascii=False),
            tokens_in,
            tokens_out,
            model_tier,
            cost_usd,
            run_id,
        ),
    )
    conn.commit()


def month_cost_usd(conn: sqlite3.Connection, year_month: str | None = None) -> float:
    ym = year_month or datetime.now(UTC).strftime("%Y-%m")
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM run WHERE substr(started_at, 1, 7) = ?", (ym,)
    ).fetchone()
    return float(row["c"])


def recent_runs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM run ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall())
