"""Configuración del asistente IA (proveedor, modelo, claves de API y, para la IA local, la
dirección del servidor y su contexto), en la carpeta del usuario.

Las claves de API se guardan cifradas para el usuario (``keystore``: DPAPI en Windows), nunca en
claro: ``<proveedor>_api_key_secret``. Una clave guardada en claro por una versión anterior
(``<proveedor>_api_key``) se cifra la primera vez que se lee. El archivo se escribe de forma
atómica y, fuera de Windows, solo lo puede leer su dueño.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pdf_core.agent import keystore
from pdf_core.agent.providers import DEFAULT_CONTEXT, PROVIDERS

log = logging.getLogger(__name__)

_STORE = Path.home() / ".extraer_pdfs_config.json"


def _load() -> dict:
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("No se pudo leer la configuración del asistente", exc_info=True)
        return {}


def _save(data: dict) -> None:
    """Escribe el archivo entero de una vez: nunca queda a medias (con una clave cortada)."""
    temporary = _STORE.with_name(f"{_STORE.name}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o600)  # en Windows, la carpeta del usuario ya es solo suya
        os.replace(temporary, _STORE)
    except OSError:
        log.warning("No se pudo guardar la configuración del asistente", exc_info=True)
        temporary.unlink(missing_ok=True)


def get_api_key(provider: str) -> str:
    data = _load()
    stored = data.get(f"{provider}_api_key_secret")
    if isinstance(stored, str) and stored:
        try:
            return keystore.reveal(stored)
        except keystore.KeystoreError:
            log.warning("No se pudo descifrar la clave de API de %s: hay que volver a escribirla", provider)
            return ""
    legacy = data.get(f"{provider}_api_key")
    if isinstance(legacy, str) and legacy:
        set_api_key(provider, legacy)  # de una versión anterior, en claro: se cifra
        return legacy
    return ""


def set_api_key(provider: str, key: str) -> None:
    data = _load()
    data.pop(f"{provider}_api_key", None)  # la de versiones anteriores, en claro
    if key:
        data[f"{provider}_api_key_secret"] = keystore.protect(key)
    else:
        data.pop(f"{provider}_api_key_secret", None)
    _save(data)


def get_provider() -> str:
    return _load().get("provider", "google")


def set_provider(provider: str) -> None:
    data = _load()
    data["provider"] = provider
    _save(data)


def get_model(provider: str) -> str:
    default = PROVIDERS[provider].model if provider in PROVIDERS else ""
    return _load().get(f"{provider}_model") or default


def set_model(provider: str, model: str) -> None:
    data = _load()
    data[f"{provider}_model"] = model
    _save(data)


def get_base_url(provider: str) -> str:
    """La dirección del servidor: la guardada si es configurable (IA local), si no la del proveedor."""
    known = PROVIDERS.get(provider)
    if known is None:
        return ""
    stored = _load().get(f"{provider}_base_url") if known.local else None
    return stored if isinstance(stored, str) and stored else known.base_url


def set_base_url(provider: str, url: str) -> None:
    """``url`` ya comprobada con ``providers.check_base_url``."""
    data = _load()
    data[f"{provider}_base_url"] = url
    _save(data)


def get_context(provider: str) -> int:
    """Tokens de contexto del modelo (IA local; los de la nube no tienen límite práctico aquí)."""
    value = _load().get(f"{provider}_context")
    return value if isinstance(value, int) and value > 0 else DEFAULT_CONTEXT


def set_context(provider: str, tokens: int) -> None:
    data = _load()
    data[f"{provider}_context"] = tokens
    _save(data)
