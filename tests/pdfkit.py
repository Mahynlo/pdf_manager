"""Crear PDF para las pruebas, con PDFium, y hablar con el motor de EmbedPDF.

Lo que el PDFium de Python no sabe hacer (cifrar, censurar, escribir marcadores) se hace con el
motor real: :func:`run_engine` ejecuta ``tests/engine_task.mjs`` en Node con el mismo código que
usa la ventana (``app/ui/src/lib/engine-tasks.ts``). Hace falta Node e instalar la interfaz.
"""
from __future__ import annotations

import ctypes
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as raw
import pytest

from pdf_core.pdf import Document, Page, Rect

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "engine_task.mjs"
ANNOT_KINDS = {
    "Text": raw.FPDF_ANNOT_TEXT, "Link": raw.FPDF_ANNOT_LINK, "Square": raw.FPDF_ANNOT_SQUARE,
    "Highlight": raw.FPDF_ANNOT_HIGHLIGHT, "Redact": raw.FPDF_ANNOT_REDACT,
}
ANNOT_NAMES = {value: name for name, value in ANNOT_KINDS.items()}


def run_engine(task: str, data: bytes, args: dict) -> bytes:
    """El ``Host.run_engine`` de las pruebas: el motor de EmbedPDF en Node."""
    if shutil.which("node") is None or not (ROOT / "app" / "ui" / "node_modules").is_dir():
        pytest.skip("hace falta Node y las dependencias de app/ui para usar el motor de EmbedPDF")
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder) / "in.pdf", Path(folder) / "out.pdf"
        source.write_bytes(data)
        done = subprocess.run(
            ["node", "--no-warnings", str(SCRIPT), task, json.dumps(args), str(source), str(target)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if done.returncode:
            raise RuntimeError(done.stderr.strip()[-400:])
        return target.read_bytes()


def add_page(doc: Document, width: float = 595, height: float = 842) -> Page:
    doc.new_page(len(doc), width, height)
    return doc[len(doc) - 1]


def add_text(page: Page, x: float, y: float, text: str, size: float = 11) -> None:
    """Escribe ``text`` con su línea base en ``(x, y)`` (origen arriba a la izquierda)."""
    doc = page.parent.raw
    font = raw.FPDFText_LoadStandardFont(doc, b"Helvetica")
    with page._opened() as opened:
        obj = raw.FPDFPageObj_CreateTextObj(doc, font, float(size))
        encoded = (text + "\0").encode("utf-16-le")
        raw.FPDFText_SetText(obj, ctypes.cast(encoded, ctypes.POINTER(raw.FPDF_WCHAR)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, float(x), float(opened.get_size()[1] - y))
        raw.FPDFPage_InsertObject(opened, obj)
        raw.FPDFPage_GenerateContent(opened)
    page._chars = page._text = None


def add_image(page: Page, rect: Rect, image: np.ndarray) -> None:
    """Pone ``image`` (RGB) en ``rect`` (coordenadas de la página sin girar)."""
    doc = page.parent.raw
    bgr = np.ascontiguousarray(image[:, :, ::-1])
    bitmap = pdfium.PdfBitmap.new_native(bgr.shape[1], bgr.shape[0], raw.FPDFBitmap_BGR)
    for row in range(bgr.shape[0]):
        start = row * bitmap.stride
        bitmap.buffer[start:start + bgr.shape[1] * 3] = bgr[row].tobytes()
    with page._opened() as opened:
        obj = pdfium.PdfImage.new(doc)
        obj.set_bitmap(bitmap)
        height = opened.get_size()[1]
        obj.set_matrix(pdfium.PdfMatrix(rect.width, 0, 0, rect.height, rect.x0, height - rect.y1))
        opened.insert_obj(obj)
        opened.gen_content()
    bitmap.close()


def add_annot(page: Page, kind: str, rect: Rect, contents: str = "") -> None:
    with page._opened() as opened:
        annot = raw.FPDFPage_CreateAnnot(opened, ANNOT_KINDS[kind])
        height = opened.get_size()[1]
        box = raw.FS_RECTF(rect.x0, height - rect.y0, rect.x1, height - rect.y1)
        raw.FPDFAnnot_SetRect(annot, box)
        if contents:
            value = (contents + "\0").encode("utf-16-le")
            raw.FPDFAnnot_SetStringValue(annot, b"Contents", ctypes.cast(value, ctypes.POINTER(raw.FPDF_WCHAR)))
        raw.FPDFPage_CloseAnnot(annot)


def annots(page: Page) -> list[str]:
    """Tipos de las anotaciones de ``page``, en orden."""
    with page._opened() as opened:
        kinds = []
        for i in range(raw.FPDFPage_GetAnnotCount(opened)):
            annot = raw.FPDFPage_GetAnnot(opened, i)
            kind = raw.FPDFAnnot_GetSubtype(annot)
            kinds.append(ANNOT_NAMES.get(kind, str(kind)))
            raw.FPDFPage_CloseAnnot(annot)
        return kinds


def delete_annots(page: Page) -> None:
    with page._opened() as opened:
        for i in reversed(range(raw.FPDFPage_GetAnnotCount(opened))):
            raw.FPDFPage_RemoveAnnot(opened, i)


def pdf_bytes(pages: list[list[tuple]], size: tuple[float, float] = (595, 842)) -> bytes:
    """Un PDF: cada página es una lista de ``(x, y, texto)``."""
    with Document.new() as doc:
        for lines in pages:
            page = add_page(doc, *size)
            for x, y, text in lines:
                add_text(page, x, y, text)
        return doc.to_bytes()


def encrypted(data: bytes, user: str, owner: str | None = None, permissions: int = 0xF3C) -> bytes:
    """``data`` cifrado con AES-256 por el motor de EmbedPDF."""
    return run_engine("encrypt", data, {"user": user, "owner": owner or user, "permissions": permissions})


def page_texts(source: str | Path | bytes, password: str | None = None) -> list[str]:
    with Document.open(source, password) as doc:
        return [page.text().strip() for page in doc]
