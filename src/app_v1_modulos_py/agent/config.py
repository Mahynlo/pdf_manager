"""Persistent API-key / agent config stored in the user's home directory."""
from __future__ import annotations

import json
from pathlib import Path

_STORE = Path.home() / ".extraer_pdfs_config.json"


def _load() -> dict:
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        _STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_api_key(provider: str) -> str:
    return _load().get(f"{provider}_api_key", "")


def set_api_key(provider: str, key: str) -> None:
    data = _load()
    data[f"{provider}_api_key"] = key
    _save(data)


def get_provider() -> str:
    return _load().get("provider", "google")


def set_provider(provider: str) -> None:
    data = _load()
    data["provider"] = provider
    _save(data)


def get_model(provider: str) -> str:
    defaults = {"google": "gemini-2.5-flash", "openai": "gpt-4o-mini"}
    return _load().get(f"{provider}_model", defaults.get(provider, ""))


def set_model(provider: str, model: str) -> None:
    data = _load()
    data[f"{provider}_model"] = model
    _save(data)
