"""Proveedores del asistente IA: todos hablan la API de OpenAI (``/chat/completions``,
``/embeddings`` y ``/models``), así un solo cliente (el SDK oficial ``openai``) sirve para
Gemini, OpenAI y los servidores locales (Ollama, LM Studio, llama.cpp, vLLM…).

Seguridad (docs/web/seguridad.md): la dirección de Gemini y de OpenAI es fija, así su clave solo
viaja a su servidor. La de la IA local la elige el usuario: ``http`` solo en el propio equipo o en
la red privada; cualquier otro servidor, solo por ``https`` (si no, el texto del PDF y la clave
viajarían sin cifrar).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_CONTEXT = 4096  # tokens: el contexto por defecto de Ollama y LM Studio
MIN_CONTEXT = 2048
MAX_CONTEXT = 2_000_000


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str  # la dirección por defecto (fija si no es ``local``)
    model: str  # el modelo por defecto ("" = hay que elegirlo)
    embedding_model: str | None  # para el chat con búsqueda semántica; sin él, búsqueda por palabras
    needs_key: bool
    local: bool = False  # dirección y contexto configurables
    fallbacks: tuple[str, ...] = ()  # se prueban si el modelo elegido no existe o no responde (503)

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "needs_key": self.needs_key, "local": self.local,
                "base_url": self.base_url, "model": self.model}


# Modelos vigentes en noviembre de 2026 (gemini-2.5-flash y text-embedding-004 ya están retirados).
# Se pueden cambiar en el panel; «Buscar» los pide al servidor. Los de ``fallbacks``, por si el
# elegido está saturado (Gemini responde 503 a menudo con sus modelos más nuevos) o ya no existe.
PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("google", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
             "gemini-3.8-flash", "gemini-embedding-2", needs_key=True,
             fallbacks=("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite")),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", "gpt-6-luna", "text-embedding-3-small",
             needs_key=True, fallbacks=("gpt-4.1-mini", "gpt-4o-mini")),
    Provider("local", "IA local", "http://localhost:11434/v1", "", None,
             needs_key=False, local=True),
)}


class BadAddress(ValueError):
    """La dirección del servidor de IA no es válida o no es segura."""


def check_base_url(url: str) -> str:
    """``url`` normalizada si se puede usar; si no, :class:`BadAddress` con el motivo."""
    url = url.strip()
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        parts.port  # noqa: B018 - valida el puerto (ValueError si no es un número válido)
    except ValueError as ex:
        raise BadAddress("La dirección del servidor no es válida.") from ex
    if parts.scheme not in ("http", "https") or not host:
        raise BadAddress("La dirección tiene que empezar por http:// o https:// e incluir el servidor.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise BadAddress("La dirección no puede llevar usuario, contraseña ni parámetros.")
    if any(ord(c) < 33 for c in url):
        raise BadAddress("La dirección no puede llevar espacios ni caracteres de control.")
    if parts.scheme == "http" and not _is_private(host):
        raise BadAddress("Un servidor fuera de este equipo o de la red local tiene que usar https://.")
    return url.rstrip("/")


def _is_private(host: str) -> bool:
    """El propio equipo o una dirección de la red privada (donde ``http`` es aceptable)."""
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # un nombre: podría resolverse a cualquier sitio
    return address.is_loopback or (address.is_private and not address.is_link_local)


def context_chars(tokens: int) -> int:
    """Caracteres de documento que caben en un contexto de ``tokens``: se reservan 1500 tokens para
    las instrucciones, el historial y la respuesta, y se cuentan ~3 caracteres por token (español)."""
    return max(tokens - 1500, 500) * 3
