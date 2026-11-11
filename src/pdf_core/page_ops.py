"""Exportaciones: el texto de unas páginas y las imágenes de un :class:`pdf_core.pdf.Document`.

Independientes de la interfaz. Las operaciones de página del visor y la extracción de una
página las hace el motor de EmbedPDF (app/ui/src/lib/pdf-engine).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pdf_core.pdf import Document


class PageWithText(Protocol):
    """Una página de la que se puede leer el texto (``Page``, ``PageText``, ``PackedPageText``)."""

    def text(self) -> str: ...


def document_text(pages: Sequence[PageWithText], ocr_text: dict[int, str] | None = None) -> str:
    """Texto de todas las páginas, con un encabezado ``=== PÁGINA n ===`` por página.

    ``ocr_text``: texto reconocido por página; se usa en las que no tienen texto nativo.
    """
    parts = []
    for i, page in enumerate(pages):
        text = page.text().strip() or (ocr_text or {}).get(i, "").strip()
        parts += [f"=== PÁGINA {i + 1} ===", text, ""]
    return "\n".join(parts)


def export_images(doc: Document, folder: Path, stem: str) -> int:
    """Guarda en ``folder`` las imágenes incrustadas (``<stem>_p<n>_img<k>.<ext>``); devuelve cuántas."""
    count = 0
    for page in doc:
        for k, (ext, data) in enumerate(page.export_images(), 1):
            (folder / f"{stem}_p{page.number + 1}_img{k}.{ext}").write_bytes(data)
            count += 1
    return count
