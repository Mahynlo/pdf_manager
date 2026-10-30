"""Preferencias persistentes de la app en un JSON del perfil de usuario."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app import DATA_DIR

log = logging.getLogger(__name__)

DEFAULT_FILE = DATA_DIR / "settings.json"


class Settings:
    def __init__(self, path: Path = DEFAULT_FILE) -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("Preferencias ilegibles en %s; se usan las de fábrica", path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError:
            log.exception("No se pudieron guardar las preferencias en %s", self._path)

    @property
    def dark_theme(self) -> bool:
        return bool(self.get("dark_theme", False))
