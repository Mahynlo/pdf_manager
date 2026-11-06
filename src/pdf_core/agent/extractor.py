"""Texto de un PDF para el agente: el de cada página, con el de OCR en las escaneadas.

Los textos reconocidos por el OCR del visor se usan en las páginas sin texto nativo.
"""
from __future__ import annotations

from pdf_core.pdf import Document


def to_pages(
    pdf_path: str,
    ocr_overrides: dict[int, str] | None = None,
    max_pages: int = 300,
) -> list[dict]:
    """Una entrada por página: ``{"metadata": {"page_number": n}, "text": texto}``."""
    result: list[dict] = []
    with Document.open(pdf_path) as doc:
        for page in list(doc)[:max_pages]:
            text = page.text().strip() or (ocr_overrides or {}).get(page.number, "").strip()
            result.append({"metadata": {"page_number": page.number + 1}, "text": text})
    return result


def to_markdown(
    pdf_path: str,
    ocr_overrides: dict[int, str] | None = None,
    max_pages: int = 300,
) -> str:
    """
    Convert a PDF to a Markdown string suitable for LLM context.

    Parameters
    ----------
    pdf_path : str
        Ruta al archivo PDF.
    ocr_overrides : dict[int, str], optional
        Texto OCR indexado por número de página (0-based).
        Se usa cuando la página no tiene texto nativo.
    max_pages : int
        Límite de páginas a procesar.

    Returns
    -------
    str
        Documento en formato Markdown listo para enviar al LLM.
    """
    parts: list[str] = []
    for page_data in to_pages(pdf_path, ocr_overrides, max_pages):
        pn: int = page_data["metadata"].get("page_number", 1)
        text: str = (page_data.get("text") or "").strip()
        if text:
            parts.append(f"<!-- Página {pn} -->\n{text}")
    return "\n\n---\n\n".join(parts) if parts else "(documento sin texto extraíble)"
