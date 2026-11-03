"""Shared fixtures: every test gets an isolated MACROWEB_DATA_DIR so nothing touches ./data."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("MACROWEB_DATA_DIR", str(data))
    monkeypatch.setenv("MACROWEB_DIGESTS_DIR", str(tmp_path / "digests"))
    monkeypatch.setenv("MACROWEB_DISABLE_LLM", "1")  # no claude -p from tests, ever
    for var in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "MACROWEB_TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    assert os.environ["MACROWEB_DATA_DIR"] == str(data)
    return data
