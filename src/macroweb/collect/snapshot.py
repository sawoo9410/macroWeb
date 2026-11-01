"""Raw snapshots: `data/raw/YYYY/MM/DD/<sha256>.<ext>.gz` + `.meta.json` (PLAN §2-1, §3.3). Content-addressed,
so re-fetching identical bytes is a no-op and `collect` stays idempotent. Snapshots are never modified."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from macroweb.paths import raw_dir


@dataclass
class SnapshotInfo:
    path: Path
    sha256: str
    size: int
    is_new: bool


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save_raw(
    source_id: str,
    url: str,
    content: bytes,
    *,
    ext: str,
    status: int,
    content_type: str,
    final_url: str | None = None,
    fetched_at: datetime | None = None,
    kind: str | None = None,
) -> SnapshotInfo:
    fetched_at = fetched_at or datetime.now(UTC)
    digest = sha256_hex(content)
    day_dir = raw_dir() / fetched_at.strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{digest}.{ext}.gz"
    is_new = not path.exists()
    if is_new:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(tmp, "wb") as fh:
            fh.write(content)
        tmp.replace(path)
        meta = {
            "source_id": source_id,
            "url": url,
            "final_url": final_url or url,
            "status": status,
            "content_type": content_type,
            "fetched_at": fetched_at.isoformat(timespec="seconds"),
            "sha256": digest,
            "size": len(content),
            "kind": kind,
        }
        path.with_name(f"{digest}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return SnapshotInfo(path=path, sha256=digest, size=len(content), is_new=is_new)


def read_raw(path: Path | str) -> bytes:
    with gzip.open(path, "rb") as fh:
        return fh.read()
