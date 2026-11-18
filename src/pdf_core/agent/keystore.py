"""Guardar secretos (las claves de API del asistente) cifrados para el usuario.

- **Windows**: DPAPI (``CryptProtectData``), el almacén del sistema para esto. Lo cifrado solo lo
  puede descifrar el mismo usuario en el mismo equipo: si se copia el archivo a otra cuenta u otro
  equipo, no sirve. Sin dependencias (ctypes).
- **Otros sistemas** (y Pyodide, en el navegador): no hay un almacén común sin dependencias; el
  secreto se guarda tal cual y quien lo guarda limita los permisos del archivo (``config.py``).

``protect`` devuelve texto (``dpapi:…`` o ``plain:…``) para guardarlo en JSON; ``reveal`` lo deshace.
"""

from __future__ import annotations

import base64
import ctypes
import os

_ENTROPY = b"Extraer PDFs: claves de API"  # otro programa del usuario no lo descifra por casualidad
_DPAPI = "dpapi:"
_PLAIN = "plain:"
_UI_FORBIDDEN = 0x1  # CRYPTPROTECT_UI_FORBIDDEN: nunca abrir un diálogo


class KeystoreError(Exception):
    """No se pudo cifrar o descifrar (p. ej. el archivo viene de otro usuario o equipo)."""


def protect(secret: str) -> str:
    data = secret.encode("utf-8")
    if os.name == "nt":
        return _DPAPI + base64.b64encode(_dpapi(data, encrypt=True)).decode("ascii")
    return _PLAIN + base64.b64encode(data).decode("ascii")


def reveal(stored: str) -> str:
    try:
        if stored.startswith(_DPAPI) and os.name == "nt":
            return _dpapi(base64.b64decode(stored[len(_DPAPI):]), encrypt=False).decode("utf-8")
        if stored.startswith(_PLAIN):
            return base64.b64decode(stored[len(_PLAIN):]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as ex:
        raise KeystoreError("El secreto guardado no es válido") from ex
    raise KeystoreError("El secreto se guardó en otro sistema")


def is_protected(stored: str) -> bool:
    """Si ``stored`` está cifrado por el sistema (y no solo guardado tal cual)."""
    return stored.startswith(_DPAPI)


# ── DPAPI ─────────────────────────────────────────────────────────────────
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(data: bytes, *, encrypt: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32  # type: ignore[attr-defined]
    source, _keep = _blob(data)
    entropy, _keep_entropy = _blob(_ENTROPY)
    result = _Blob()
    call = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    description = ctypes.c_wchar_p("Extraer PDFs") if encrypt else None
    if not call(ctypes.byref(source), description, ctypes.byref(entropy), None, None, _UI_FORBIDDEN, ctypes.byref(result)):
        raise KeystoreError(f"DPAPI falló (error {ctypes.GetLastError()})")  # type: ignore[attr-defined]
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
