"""Caché del navegador de la ventana (WebView2) frente a versiones nuevas del frontend.

El servidor HTTP de pywebview sirve el frontend sin ``Cache-Control`` (lo intenta,
pero ``bottle.static_file`` descarta esa cabecera). Sin ella, WebView2 puede seguir
usando copias antiguas de los módulos JS/CSS durante horas o días, aunque se
reinicie la app: un módulo nuevo pediría cosas que la copia antigua de otro no tiene
(«does not provide an export named …»).

Por eso, al arrancar, si los archivos del frontend cambiaron desde el último
arranque se borra la caché HTTP del navegador (solo la caché: preferencias y
almacenamiento local se conservan).
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_DIRS = ("Cache", "Code Cache")  # dentro de <storage>/EBWebView/Default
STAMP_FILE = "frontend.stamp"


def frontend_fingerprint(frontend_dir: Path) -> str:
    """Huella de los archivos del frontend (ruta, tamaño y fecha de modificación)."""
    digest = hashlib.sha256()
    for path in sorted(p for p in frontend_dir.rglob("*") if p.is_file()):
        stat = path.stat()
        digest.update(f"{path.relative_to(frontend_dir).as_posix()}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def discard_stale_cache(frontend_dir: Path, storage_dir: Path) -> bool:
    """Borra la caché de WebView2 si el frontend cambió desde el último arranque. True si la borró."""
    stamp = storage_dir / STAMP_FILE
    current = frontend_fingerprint(frontend_dir)
    try:
        if stamp.read_text(encoding="utf-8") == current:
            return False
    except OSError:
        pass  # primer arranque o sello ilegible: se trata como cambio
    profile = storage_dir / "EBWebView" / "Default"
    for name in CACHE_DIRS:
        shutil.rmtree(profile / name, ignore_errors=True)
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        stamp.write_text(current, encoding="utf-8")
    except OSError:
        log.warning("No se pudo guardar la huella del frontend en %s", stamp, exc_info=True)
    log.info("Frontend nuevo: caché de WebView2 descartada")
    return True
