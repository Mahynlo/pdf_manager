"""Persistent recent-files list stored as JSON in the user's home directory.

Whether a listed file still exists is decided by *exists* (default: it is a file on disk). The app
passes its host's check instead, because in the browser the files live in the window, not on the
disk Python sees.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

_MAX = 20
_STORE = Path.home() / ".extraer_pdfs_recent.json"


def _normalize(p: str) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return os.path.normpath(p)


def _on_disk(path: str) -> bool:
    return Path(path).is_file()


def _key(path: str) -> str:
    return path.lower() if os.name == "nt" else path


def _read() -> list[str]:
    """The stored list, normalized and deduplicated, whether the files exist or not."""
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
                    if _key(norm) not in seen:
                        seen.add(_key(norm))
                        result.append(norm)
            return result
    except Exception:
        pass
    return []


def load(exists: Callable[[str], bool] = _on_disk) -> list[str]:
    """Return the recent-files list (only paths that still exist, according to *exists*)."""
    try:
        return [p for p in _read() if exists(p)][:_MAX]
    except Exception:
        return []


def push(path: str, exists: Callable[[str], bool] = _on_disk) -> None:
    """Add *path* to the front of the list, deduplicate, and persist."""
    if not path:
        return
    try:
        norm_path = _normalize(path)
        if not exists(norm_path):
            return

        norm_key = _key(norm_path)
        existing = [p for p in load(exists) if _key(p) != norm_key]
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
        existing = [p for p in _read() if _key(p) != _key(norm_path)]
        _STORE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear() -> None:
    """Clear all recent files."""
    try:
        _STORE.write_text("[]", encoding="utf-8")
    except Exception:
        pass
