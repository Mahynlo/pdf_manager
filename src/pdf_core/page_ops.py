"""Operaciones de página y exportaciones sobre un ``fitz.Document`` abierto.

Independientes de la interfaz (equivalen a ``_page_ops_mixin.py`` y a la parte de
exportación de ``_file_ops_mixin.py`` en Qt). Los índices son 0-based; quien
llama valida el rango y decide qué página mostrar después.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import fitz


def rotate_pages(doc: fitz.Document, pages: Iterable[int], angle: int) -> None:
    """Suma ``angle`` (múltiplo de 90, negativo = antihorario) a la rotación de ``pages``."""
    for index in pages:
        page = doc[index]
        page.set_rotation((page.rotation + angle) % 360)


def insert_blank_page(doc: fitz.Document, after: int) -> int:
    """Inserta una página en blanco del tamaño de ``after`` justo detrás; devuelve su índice."""
    ref = doc[after].rect
    doc.new_page(pno=after + 1, width=ref.width, height=ref.height)
    return after + 1


def duplicate_page(doc: fitz.Document, index: int) -> int:
    """Inserta una copia de ``index`` justo detrás; devuelve el índice de la copia."""
    with fitz.open() as tmp:
        tmp.insert_pdf(doc, from_page=index, to_page=index)
        doc.insert_pdf(tmp, from_page=0, to_page=0, start_at=index + 1)
    return index + 1


def move_page(doc: fitz.Document, src: int, dst: int) -> None:
    """Mueve la página ``src`` para que quede en la posición final ``dst``."""
    if src == dst:
        return
    # fitz.move_page(pno, to) inserta *antes* de ``to``; -1 = al final.
    if dst > src:
        to = dst + 1 if dst + 1 < len(doc) else -1
    else:
        to = dst
    doc.move_page(src, to)


def extract_pages(doc: fitz.Document, pages: Iterable[int]) -> bytes:
    """Las páginas indicadas como un PDF nuevo (sin cifrar)."""
    with fitz.open() as out:
        for index in pages:
            out.insert_pdf(doc, from_page=index, to_page=index)
        return out.tobytes(garbage=4, deflate=True)


def document_text(doc: fitz.Document, ocr_text: dict[int, str] | None = None) -> str:
    """Texto de todas las páginas, con un encabezado ``=== PÁGINA n ===`` por página.

    ``ocr_text``: texto reconocido por página; se usa en las que no tienen texto nativo.
    """
    parts = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip() or (ocr_text or {}).get(i, "").strip()
        parts += [f"=== PÁGINA {i + 1} ===", text, ""]
    return "\n".join(parts)


def export_images(doc: fitz.Document, folder: Path, stem: str) -> int:
    """Guarda en ``folder`` las imágenes incrustadas (``<stem>_p<n>_img<k>.<ext>``); devuelve cuántas."""
    count = 0
    for pno, page in enumerate(doc):
        for img_idx, img in enumerate(page.get_images(full=True)):
            image = doc.extract_image(img[0])
            if not image:
                continue
            (folder / f"{stem}_p{pno + 1}_img{img_idx + 1}.{image['ext']}").write_bytes(image["image"])
            count += 1
    return count
