"""Persistent recent-files list stored as JSON in the user's home directory."""

from __future__ import annotations

import json
import os
from pathlib import Path

_MAX = 20
_STORE = Path.home() / ".extraer_pdfs_recent.json"


def _normalize(p: str) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return os.path.normpath(p)


def load() -> list[str]:
    """Return the recent-files list (only paths that still exist on disk)."""
    try:
        if not _STORE.exists():
            return []
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            result: list[str] = []
            seen: set[str] = set()
            for p in data:
                if isinstance(p, str):
                    norm = _normalize(p)
                    norm_key = norm.lower() if os.name == "nt" else norm
                    if norm_key not in seen and Path(norm).is_file():
                        seen.add(norm_key)
                        result.append(norm)
            return result[:_MAX]
    except Exception:
        pass
    return []


def push(path: str) -> None:
    """Add *path* to the front of the list, deduplicate, and persist."""
    if not path:
        return
    try:
        norm_path = _normalize(path)
        if not Path(norm_path).exists():
            return

        norm_key = norm_path.lower() if os.name == "nt" else norm_path
        existing = [
            p for p in load()
            if (p.lower() if os.name == "nt" else p) != norm_key
        ]
        new_list = [norm_path, *existing][:_MAX]
        _STORE.write_text(json.dumps(new_list, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def remove(path: str) -> None:
    """Remove *path* from the recent-files list and persist."""
    if not path:
        return
    try:
        norm_path = _normalize(path)
        norm_key = norm_path.lower() if os.name == "nt" else norm_path
        existing = [
            p for p in load()
            if (p.lower() if os.name == "nt" else p) != norm_key
        ]
        _STORE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear() -> None:
    """Clear all recent files."""
    try:
        _STORE.write_text("[]", encoding="utf-8")
    except Exception:
        pass
