"""Censura: buscar lo que hay que tapar y aplicarlo de forma irreversible.

Criterios: frases (sin tildes y, si se pide,
sin distinguir mayúsculas), palabras completas, expresiones regulares y palabras
reconocidas por OCR.

Las coordenadas de :func:`find_in_page` son las de la página sin girar; las de
:func:`find_in_ocr`, las de la página tal como se ve (como las palabras de OCR). Las marcas
de censura las aplica el motor de EmbedPDF (``ViewerService.apply_redaction_marks``).
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

from pdf_core.pdf import Page, Rect, TextMap
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
    """Un término con caracteres especiales de regex se trata como patrón."""
    return any(ch in _REGEX_CHARS for ch in term)


def find_in_page(
    page: Page,
    term: str,
    *,
    case_sensitive: bool,
    whole_word: bool,
    regex: bool,
    text: TextMap | None = None,
) -> list[Rect]:
    """Rectángulos (sin girar) donde aparece ``term`` en el texto nativo de ``page``; uno por línea.

    Una frase se encuentra también partida en varias líneas. ``text``: ``page.text_map()`` ya
    extraído (para no repetirlo por término).
    """
    q = term.strip()
    if not q:
        return []
    found = page.text_map() if text is None else text
    flags = 0 if case_sensitive else re.IGNORECASE
    subject = found.text
    if regex:
        try:
            pattern = re.compile(q, flags)
        except re.error:
            return []  # patrón incompleto mientras se escribe
    else:
        # Sin tildes (la tabla es 1:1: las posiciones siguen valiendo para el texto original).
        subject = fold_accents(subject)
        body = r"\s+".join(re.escape(fold_accents(word)) for word in q.split())
        pattern = re.compile(rf"(?<!\w){body}(?!\w)" if whole_word else body, flags)
    rects: list[Rect] = []
    for match in pattern.finditer(subject):
        rects += found.rects_of(match.start(), match.end())
    return rects


def find_in_ocr(
    words: Iterable[tuple], term: str, *, case_sensitive: bool, whole_word: bool, regex: bool
) -> list[Rect]:
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
    rects: list[Rect] = []
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
            rects.append(Rect(w[0], w[1], w[2], w[3]))
    return rects
