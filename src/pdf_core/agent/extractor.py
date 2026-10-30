"""PDF to Markdown conversion using PyMuPDF4LLM.

Replaces the raw fitz text extraction with a Markdown-aware pipeline
that preserves tables, headings and document structure — much better
input quality for LLMs.

OCR overrides (from the viewer's OCR engine) are injected for pages
that have no native text (scanned documents).
"""
from __future__ import annotations

import pymupdf4llm


def to_pages(
    pdf_path: str,
    ocr_overrides: dict[int, str] | None = None,
    max_pages: int = 300,
) -> list[dict]:
    """
    Return raw page_chunks from pymupdf4llm with OCR overrides applied.

    Each element is a dict with keys ``"metadata"`` (page_number, etc.)
    and ``"text"`` (Markdown for that page).
    """
    pages: list[dict] = pymupdf4llm.to_markdown(
        pdf_path,
        page_chunks=True,
        show_progress=False,
    )
    result: list[dict] = []
    for page_data in pages[:max_pages]:
        pn_0: int = page_data["metadata"].get("page_number", 1) - 1
        text: str = (page_data.get("text") or "").strip()
        if not text and ocr_overrides and pn_0 in ocr_overrides:
            page_data = {**page_data, "text": ocr_overrides[pn_0].strip()}
        result.append(page_data)
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
