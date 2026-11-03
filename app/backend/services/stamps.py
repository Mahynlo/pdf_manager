"""Servicio ``stamps``: los sellos propios y las firmas guardadas del visor.

El visor los crea con EmbedPDF (``plugin-stamp`` y ``plugin-signature``) y aquí solo se
guardan, para que sigan ahí al volver a abrir la app:

- **Sellos propios:** la biblioteca de EmbedPDF tal cual, un PDF con una página por sello
  (``custom.pdf``) y la lista de sellos (``custom.json``: nombre y página de cada uno).
- **Firmas:** las que el usuario decidió guardar, en el formato de ``serializeEntries`` de
  EmbedPDF (``signatures.json``: trazos o imagen en base64). Se quedan en este equipo.

Los sellos de texto (leyendas) siguen en el servicio ``legends``, compartido con Qt.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from pathlib import Path
from typing import Any

from app import DATA_DIR
from app.backend.rpc import UserError, exposed

log = logging.getLogger(__name__)

STORE: Path = DATA_DIR / "stamps"  # los tests lo redirigen a una carpeta temporal
_LIBRARY_PDF = "custom.pdf"
_LIBRARY_LIST = "custom.json"
_SIGNATURES = "signatures.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        log.exception("No se pudo leer %s", path)
        return default


def _write(path: Path, data: bytes) -> None:
    """Escribe en un temporal y lo cambia de nombre: un corte a medias no deja el archivo roto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


class StampsService:
    # ── Sellos propios ─────────────────────────────────────────────────────
    @exposed
    def library(self) -> dict[str, Any] | None:
        """La biblioteca guardada: ``{pdf: base64, stamps: [...]}``, o ``None`` si no hay."""
        pdf = STORE / _LIBRARY_PDF
        stamps = _read_json(STORE / _LIBRARY_LIST, [])
        if not stamps or not pdf.is_file():
            return None
        return {"pdf": base64.b64encode(pdf.read_bytes()).decode("ascii"), "stamps": stamps}

    @exposed
    def save_library(self, pdf: str | None, stamps: list[dict[str, Any]]) -> None:
        """Guarda la biblioteca exportada por EmbedPDF (``pdf`` en base64); sin sellos, la borra."""
        if not stamps:
            for name in (_LIBRARY_PDF, _LIBRARY_LIST):
                (STORE / name).unlink(missing_ok=True)
            return
        try:
            data = base64.b64decode(pdf or "", validate=True)
        except (binascii.Error, ValueError) as err:
            raise UserError("La biblioteca de sellos no es válida.", "bad_library") from err
        if not data.startswith(b"%PDF"):
            raise UserError("La biblioteca de sellos no es válida.", "bad_library")
        _write(STORE / _LIBRARY_PDF, data)
        _write(STORE / _LIBRARY_LIST, json.dumps(stamps, ensure_ascii=False, indent=1).encode("utf-8"))

    # ── Firmas ─────────────────────────────────────────────────────────────
    @exposed
    def signatures(self) -> list[dict[str, Any]]:
        """Las firmas guardadas (formato de ``serializeEntries``)."""
        entries = _read_json(STORE / _SIGNATURES, [])
        return entries if isinstance(entries, list) else []

    @exposed
    def save_signatures(self, entries: list[dict[str, Any]]) -> None:
        """Sustituye las firmas guardadas; una lista vacía borra el archivo."""
        path = STORE / _SIGNATURES
        if not entries:
            path.unlink(missing_ok=True)
            return
        _write(path, json.dumps(entries, ensure_ascii=False).encode("utf-8"))
