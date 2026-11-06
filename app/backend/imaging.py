"""Páginas de PDF como imágenes listas para un ``<img src>`` del frontend."""

from __future__ import annotations

import base64

from pdf_core.pdf import Page, png


def page_data_url(page: Page, scale: float, rotation: int = 0, annots: bool = True) -> str:
    """Rasteriza ``page`` (1.0 = 72 DPI), girada ``rotation`` grados, como data URL PNG.

    ``annots=False`` omite las anotaciones (el visor dibuja encima las editables).
    """
    data = base64.b64encode(png(page.render(scale, rotation=rotation, annots=annots))).decode("ascii")
    return f"data:image/png;base64,{data}"
