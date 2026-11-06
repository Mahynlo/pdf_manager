"""Operaciones de página y exportaciones sobre un :class:`pdf_core.pdf.Document` abierto.

Independientes de la interfaz. Los índices son 0-based; quien llama valida el rango y decide
qué página mostrar después.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pdf_core.pdf import Document


def rotate_pages(doc: Document, pages: Iterable[int], angle: int) -> None:
    """Suma ``angle`` (múltiplo de 90, negativo = antihorario) a la rotación de ``pages``."""
    for index in pages:
        page = doc[index]
        page.set_rotation((page.rotation + angle) % 360)


def insert_blank_page(doc: Document, after: int) -> int:
    """Inserta una página en blanco del tamaño de ``after`` justo detrás; devuelve su índice."""
    ref = doc[after].rect
    doc.new_page(after + 1, ref.width, ref.height)
    return after + 1


def duplicate_page(doc: Document, index: int) -> int:
    """Inserta una copia de ``index`` justo detrás; devuelve el índice de la copia."""
    doc.insert_pages(doc, [index], index + 1)
    return index + 1


def extract_pages(doc: Document, pages: Iterable[int]) -> bytes:
    """Las páginas indicadas (con sus anotaciones) como un PDF nuevo sin cifrar."""
    with Document.new() as out:
        out.insert_pages(doc, list(pages))
        return out.to_bytes()


def document_text(doc: Document, ocr_text: dict[int, str] | None = None) -> str:
    """Texto de todas las páginas, con un encabezado ``=== PÁGINA n ===`` por página.

    ``ocr_text``: texto reconocido por página; se usa en las que no tienen texto nativo.
    """
    parts = []
    for i, page in enumerate(doc):
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
