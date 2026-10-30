"""Rutas PDF recibidas al lanzar la app ("Abrir con", línea de comandos, launcher).

Equivale a ``_collect_initial_paths`` de la versión Flet: acepta rutas directas
en ``argv`` y la variable ``EXTRAR_PDF_PATH`` (rutas separadas por ``|``) que
fija ``launcher/launcher.c``. Los flags (``--algo``) se ignoran.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

ENV_VAR = "EXTRAR_PDF_PATH"


def clean_pdf_path(arg: str) -> str | None:
    """Ruta absoluta de un PDF existente, o ``None`` si ``arg`` no lo es."""
    clean = arg.strip(" \"'`\r\n")
    if not clean.lower().endswith(".pdf"):
        return None
    try:
        path = Path(clean).resolve()
    except (OSError, ValueError):
        return None
    return str(path) if path.is_file() else None


def collect_pdf_paths(argv: Iterable[str], environ: Mapping[str, str] = os.environ) -> list[str]:
    """Rutas PDF válidas (sin duplicados, en orden) de ``argv[1:]`` y del entorno."""
    candidates = [a for a in list(argv)[1:] if not a.startswith("--")]
    candidates += environ.get(ENV_VAR, "").split("|")
    paths: list[str] = []
    for raw in candidates:
        cleaned = clean_pdf_path(raw) if raw.strip() else None
        if cleaned and cleaned not in paths:
            paths.append(cleaned)
    return paths
