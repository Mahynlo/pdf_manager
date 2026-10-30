"""Censura: buscar lo que hay que tapar y aplicarlo de forma irreversible.

Mismos criterios que el panel de censura de Qt: frases (sin tildes y, si se pide,
sin distinguir mayúsculas), palabras completas, expresiones regulares y palabras
reconocidas por OCR.

Las coordenadas de :func:`find_in_page` son las de la página sin girar (las de
PyMuPDF); las de :func:`find_in_ocr`, las de la página tal como se ve (como las
palabras de OCR). :func:`apply_marks` aplica las marcas de censura (anotaciones
``Redact``) que ya tiene la página.
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

import fitz

from pdf_core.text_utils import fold_accents

# Patrones predefinidos de datos personales (menú ⚡ del panel).
PII_PATTERNS = [
    ("📧 Correos electrónicos", r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    ("🪪 DNI / NIE (España)", r"\b(?:\d{8}[A-HJ-NP-TV-Z]|[XYZ]\d{7}[A-HJ-NP-TV-Z])\b"),
    ("📞 Teléfonos", r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"),
    ("💳 Tarjetas de crédito / débito", r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    ("📅 Fechas (DD/MM/YYYY)", r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    ("🌐 Direcciones IP (IPv4)", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("🏛️ Cuentas bancarias / IBAN", r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"),
    ("🆔 RFC / CURP (México)", r"\b[A-Z]{4}\d{6}[A-Z0-9]{3}\b|\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b"),
]
_REGEX_CHARS = frozenset("\\^$*+?[](){}|")


def looks_like_regex(term: str) -> bool:
    """Un término con caracteres especiales de regex se trata como patrón (como en Qt)."""
    return any(ch in _REGEX_CHARS for ch in term)


def _locate(page: fitz.Page, text: str, case_sensitive: bool) -> list[fitz.Rect]:
    """Rectángulos de ``text`` en la página. ``search_for`` nunca distingue mayúsculas:
    con ``case_sensitive`` se descartan los que no tienen exactamente ese texto."""
    rects = [fitz.Rect(r) for r in page.search_for(text)]
    if case_sensitive:
        # Una coincidencia partida en varias líneas da un rectángulo por línea: cada trozo
        # debe ser parte del texto buscado.
        rects = [r for r in rects if (box := page.get_textbox(r).strip()) and box in text]
    return rects


def find_in_page(
    page: fitz.Page,
    term: str,
    *,
    case_sensitive: bool,
    whole_word: bool,
    regex: bool,
    text: str | None = None,
) -> list[fitz.Rect]:
    """Rectángulos (sin girar) donde aparece ``term`` en el texto nativo de ``page``.

    ``text``: ``page.get_text("text")`` ya extraído (para no repetirlo por término).
    """
    q = term.strip()
    if not q:
        return []
    page_text = page.get_text("text") if text is None else text
    rects: list[fitz.Rect] = []
    flags = 0 if case_sensitive else re.IGNORECASE

    if regex:
        try:
            pattern = re.compile(q, flags)
        except re.error:
            return []  # patrón incompleto mientras se escribe
        seen: set[str] = set()
        for m in pattern.finditer(page_text):
            found = m.group(0).strip()
            if found and found not in seen:
                seen.add(found)
                rects.extend(_locate(page, found, case_sensitive))
        return rects

    if not whole_word:
        if case_sensitive:
            rects = _locate(page, q, True)
        else:
            # Se busca sin tildes ni mayúsculas y se localiza cada variante encontrada.
            folded_text = fold_accents(page_text)
            seen = set()
            for m in re.finditer(re.escape(fold_accents(q)), folded_text, re.IGNORECASE):
                variant = page_text[m.start():m.end()]
                if variant not in seen:
                    seen.add(variant)
                    rects.extend(fitz.Rect(r) for r in page.search_for(variant))
            if not rects:
                rects = [fitz.Rect(r) for r in page.search_for(q)]
        if rects:
            return rects

    # Por palabras: frases partidas en varias líneas y palabras completas.
    words = page.get_text("words")
    q_words = q.split()
    if not words or not q_words:
        return []

    def norm(word: str) -> str:
        word = fold_accents(word.strip(string.punctuation))
        return word if case_sensitive else word.lower()

    wanted = [norm(w) for w in q_words]
    n = len(wanted)
    for i in range(len(words) - n + 1):
        chunk = words[i:i + n]
        if [norm(w[4]) for w in chunk] != wanted:
            continue
        lines: dict[tuple, list] = {}
        for w in chunk:
            lines.setdefault((w[5], w[6]), []).append(w)  # un rectángulo por línea
        for run in lines.values():
            rects.append(fitz.Rect(min(w[0] for w in run), min(w[1] for w in run),
                                   max(w[2] for w in run), max(w[3] for w in run)))
    return rects


def find_in_ocr(
    words: Iterable[tuple], term: str, *, case_sensitive: bool, whole_word: bool, regex: bool
) -> list[fitz.Rect]:
    """Palabras de OCR (``(x0, y0, x1, y1, texto)``) que coinciden con ``term``."""
    q = term.strip()
    if not q:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = None
    if regex:
        try:
            pattern = re.compile(q, flags)
        except re.error:
            return []
    rects: list[fitz.Rect] = []
    for w in words:
        text = str(w[4]) if len(w) >= 5 else ""
        if not text:
            continue
        if pattern is not None:
            hit = bool(pattern.search(text))
        elif whole_word:
            a, b = fold_accents(text.strip(string.punctuation)), fold_accents(q.strip(string.punctuation))
            hit = a == b if case_sensitive else a.lower() == b.lower()
        else:
            a, b = fold_accents(text), fold_accents(q)
            hit = b in a if case_sensitive else b.lower() in a.lower()
        if hit:
            rects.append(fitz.Rect(w[0], w[1], w[2], w[3]))
    return rects


def apply_marks(page: fitz.Page) -> list[fitz.Rect]:
    """Aplica las marcas de censura de ``page``: cada una se tapa con su color de relleno y lo
    que hay debajo (texto, imágenes, dibujos) se borra para siempre. Devuelve los rectángulos
    (sin girar) de las marcas aplicadas."""
    rects = []
    for annot in page.annots(types=[fitz.PDF_ANNOT_REDACT]):
        rects.append(fitz.Rect(annot.rect))
        # La apariencia de la marca ya tapada (/RO, la escribe EmbedPDF) no la usa MuPDF, que
        # avisaba por consola de cada una.
        page.parent.xref_set_key(annot.xref, "RO", "null")
    if rects:
        page.apply_redactions()
    return rects
