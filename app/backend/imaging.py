"""Páginas de PDF como imágenes listas para un ``<img src>`` del frontend."""

from __future__ import annotations

import base64

import fitz


def page_data_url(
    page: fitz.Page, scale: float, rotation: int = 0, quality: int = 80, annots: bool = True
) -> str:
    """Rasteriza ``page`` (1.0 = 72 DPI), girada ``rotation`` grados, como data URL JPEG.

    JPEG en vez de PNG: las miniaturas pesan ~5× menos y viajan como texto por el puente.
    ``annots=False`` omite las anotaciones (el visor dibuja encima las editables).
    """
    matrix = fitz.Matrix(scale, scale)
    if rotation:
        matrix = matrix.prerotate(rotation)
    pix = page.get_pixmap(matrix=matrix, alpha=False, annots=annots)
    data = base64.b64encode(pix.tobytes("jpg", jpg_quality=quality)).decode("ascii")
    return f"data:image/jpeg;base64,{data}"
