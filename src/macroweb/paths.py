"""Repository and data paths. Data lives outside git (data/, logs/, private/)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
DOCS_DIR = ROOT / "docs"
SEED_DIR = ROOT / "seed"
LAUNCHD_DIR = ROOT / "launchd"
LOGS_DIR = ROOT / "logs"
PRIVATE_DIR = ROOT / "private"
CLAUDE_DIR = ROOT / ".claude"
REPORTS_DIR = ROOT / "reports"
PHASE_STATUS = DOCS_DIR / "phase_status.json"


def data_dir() -> Path:
    """`MACROWEB_DATA_DIR` overrides the default `<repo>/data`."""
    return Path(os.environ.get("MACROWEB_DATA_DIR", ROOT / "data")).expanduser()


def db_path() -> Path:
    return data_dir() / "db" / "macroweb.sqlite"


def raw_dir() -> Path:
    return data_dir() / "raw"


def digests_dir() -> Path:
    """`MACROWEB_DIGESTS_DIR` overrides `<repo>/digests` (tests point it at a temp dir)."""
    return Path(os.environ.get("MACROWEB_DIGESTS_DIR", ROOT / "digests")).expanduser()
