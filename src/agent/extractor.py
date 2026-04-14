"""PDF to Markdown conversion using PyMuPDF4LLM.

Replaces the raw fitz text extraction with a Markdown-aware pipeline
that preserves tables, headings and document structure — much better
input quality for LLMs.

OCR overrides (from the viewer's OCR engine) are injected for pages
that have no native text (scanned documents).
"""
from __future__ import annotations

import pymupdf4llm


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
    # pymupdf4llm con page_chunks=True devuelve una lista de dicts,
    # uno por página: {"metadata": {"page": 0, ...}, "text": "..."}
    pages: list[dict] = pymupdf4llm.to_markdown(
        pdf_path,
        page_chunks=True,
        show_progress=False,
    )

    parts: list[str] = []
    for page_data in pages[:max_pages]:
        # pymupdf4llm devuelve page_number con base 1
        page_num_1based: int = page_data["metadata"].get("page_number", 1)
        page_num_0based: int = page_num_1based - 1
        text: str = (page_data.get("text") or "").strip()

        # Para páginas sin texto nativo, usar el texto OCR si está disponible
        if not text and ocr_overrides and page_num_0based in ocr_overrides:
            text = ocr_overrides[page_num_0based].strip()

        if text:
            parts.append(f"<!-- Página {page_num_1based} -->\n{text}")

    return "\n\n---\n\n".join(parts) if parts else "(documento sin texto extraíble)"
