"""Persistent recent-files list stored as JSON in the user's home directory."""

from __future__ import annotations

import json
from pathlib import Path

_MAX = 12
_STORE = Path.home() / ".extraer_pdfs_recent.json"


def load() -> list[str]:
    """Return the recent-files list (only paths that still exist on disk)."""
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [p for p in data if isinstance(p, str) and Path(p).exists()][:_MAX]
    except Exception:
        pass
    return []


def push(path: str) -> None:
    """Add *path* to the front of the list, deduplicate, and persist."""
    existing = [p for p in load() if p != path]
    try:
        _STORE.write_text(json.dumps([path, *existing][:_MAX]), encoding="utf-8")
    except Exception:
        pass
