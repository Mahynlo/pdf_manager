"""Texto de una página en orden de lectura.

``page_words`` extrae los caracteres de la página (y las palabras de OCR que no
tapen texto nativo) ordenados por columnas y líneas; es la base de la selección
de texto del visor Qt. ``TextLayer`` añade el separador que va delante de cada
carácter (``""``, espacio o salto de línea) y el texto completo, que usan el
asistente IA y el panel de OCR de la versión web (la selección y la búsqueda del visor web
son de EmbedPDF).

``embed_ocr_words`` escribe en la página las palabras de OCR como texto invisible,
para que un lector de PDF (el visor con EmbedPDF) las seleccione como texto nativo.

Las coordenadas son las de la página tal como se ve (ya girada), en puntos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import fitz

from pdf_core.reading_order import (
    assign_line_indices,
    sort_words_clustered,
    sort_words_column_aware,
)

log = logging.getLogger(__name__)

Word = tuple  # (fitz.Rect, texto, inicio_de_palabra, línea)


def reads_unrotated(page: fitz.Page, has_ocr: bool) -> bool:
    """True si el orden de lectura se calcula sobre la página sin girar.

    El texto nativo de una página girada se lee en su orientación original; las
    palabras de OCR ya vienen en la orientación en que se ve la página.
    """
    return bool(page.rotation) and not has_ocr


def _ocr_word(word: tuple) -> tuple[fitz.Rect, str]:
    if isinstance(word[0], (int, float)):
        return fitz.Rect(word[0], word[1], word[2], word[3]), str(word[4]).strip()
    return fitz.Rect(word[0]), str(word[1]).strip()


def _rawdict(page: fitz.Page) -> dict:
    """``get_text("rawdict")`` con la altura de los caracteres ajustada a su glifo."""
    tools = fitz.TOOLS
    old_sgh = tools.set_small_glyph_heights()
    tools.set_small_glyph_heights(True)
    try:
        return page.get_text("rawdict")
    finally:
        tools.set_small_glyph_heights(old_sgh)


def _coverage(native: list[fitz.Rect]):
    """Función que dice si un rectángulo queda tapado (40 % o más) por los de ``native``."""
    native_bands: dict[int, list[fitz.Rect]] = {}
    for r in native:
        for bi in range(int(r.y0 // 10), int(r.y1 // 10) + 1):
            native_bands.setdefault(bi, []).append(r)

    def covered_by_native(rect: fitz.Rect) -> bool:
        area = rect.get_area()
        if area <= 0 or not native_bands:
            return False
        seen: set[int] = set()
        covered = 0.0
        for bi in range(int(rect.y0 // 10), int(rect.y1 // 10) + 1):
            for nr in native_bands.get(bi, ()):
                if id(nr) in seen:
                    continue
                ix = min(rect.x1, nr.x1) - max(rect.x0, nr.x0)
                iy = min(rect.y1, nr.y1) - max(rect.y0, nr.y0)
                if ix > 0 and iy > 0:
                    seen.add(id(nr))
                    covered += ix * iy
                    if covered >= area * 0.4:
                        return True
        return False

    return covered_by_native


def page_words(page: fitz.Page, ocr_words: list[tuple] | None = None) -> list[Word]:
    """Caracteres de la página (más palabras de OCR) en orden de lectura.

    Cada elemento es ``(rect, texto, inicio_de_palabra, línea)``; ``rect`` está en
    coordenadas de la página girada.
    """
    page_width = page.rect.width
    rot_mat = page.rotation_matrix
    raw_dict = _rawdict(page)

    words: list[tuple] = []
    gids: list[int] = []
    gid = 0
    for block in raw_dict.get("blocks", []):
        for line in block.get("lines", []):
            gid += 1
            pending_space = False
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    c = char.get("c", "")
                    if not c.strip():
                        pending_space = True
                        continue
                    if pending_space:
                        gid += 1
                    words.append((fitz.Rect(char["bbox"]) * rot_mat, c, pending_space))
                    gids.append(gid)
                    pending_space = False

    if ocr_words:
        covered_by_native = _coverage([r for r, *_ in words])
        for ocr_w in ocr_words:
            ocr_rect, ocr_txt = _ocr_word(ocr_w)
            if ocr_txt and not covered_by_native(ocr_rect):
                gid += 1
                words.append((ocr_rect, ocr_txt, True))
                gids.append(gid)

    if not words:
        try:
            for w in page.get_text("words"):
                gid += 1
                words.append((fitz.Rect(w[0], w[1], w[2], w[3]) * rot_mat, w[4], True))
                gids.append(gid)
        except Exception:
            log.debug("Sin palabras extraíbles en la página %s", page.number, exc_info=True)

    if reads_unrotated(page, bool(ocr_words)):
        derot = page.derotation_matrix
        sort_w = page.rect.height if page.rotation in (90, 270) else page_width

        def pos(r: fitz.Rect) -> fitz.Rect:
            return fitz.Rect(r) * derot

        words = sort_words_column_aware(words, sort_w, pos=pos, groups=gids)
        return assign_line_indices(words, pos=pos)
    if ocr_words:
        return sort_words_clustered(words, page_width, groups=gids)
    words = sort_words_column_aware(words, page_width, groups=gids)
    return assign_line_indices(words)


def embed_ocr_words(page: fitz.Page, ocr_words: list[tuple]) -> int:
    """Escribe en ``page`` como texto invisible las palabras de OCR que no tapan texto nativo.

    Cada palabra ocupa su rectángulo (en la página tal como se ve) y se lee en el sentido en
    que se ve la página. Devuelve cuántas escribió.
    """
    rot_mat = page.rotation_matrix
    native = [
        fitz.Rect(char["bbox"]) * rot_mat
        for block in _rawdict(page).get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        for char in span.get("chars", [])
        if char.get("c", "").strip()
    ]
    covered_by_native = _coverage(native)
    font = fitz.Font("helv")
    written = 0
    for word in ocr_words:
        rect, text = _ocr_word(word)
        if not text or rect.is_empty or covered_by_native(rect):
            continue
        size = rect.height / (font.ascender - font.descender)
        width = font.text_length(text, fontsize=size)
        if width <= 0:
            continue
        # Estirada en el sentido del texto tal como se ve, sea cual sea el giro de la página.
        stretch = rot_mat * fitz.Matrix(rect.width / width, 1) * page.derotation_matrix
        origin = fitz.Point(rect.x0, rect.y1 + font.descender * size) * page.derotation_matrix
        page.insert_text(
            origin, text, fontsize=size, fontname="helv", render_mode=3, rotate=page.rotation,
            morph=(origin, fitz.Matrix(stretch.a, stretch.b, stretch.c, stretch.d, 0, 0)),
        )
        written += 1
    return written


@dataclass
class TextLayer:
    """Texto seleccionable de una página: un elemento por carácter (o palabra de OCR)."""

    chars: list[str] = field(default_factory=list)
    rects: list[fitz.Rect] = field(default_factory=list)
    seps: list[str] = field(default_factory=list)  # separador delante de cada carácter
    text: str = ""  # "".join(sep + carácter)


def build_text_layer(page: fitz.Page, ocr_words: list[tuple] | None = None) -> TextLayer:
    """Capa de texto de ``page`` con los mismos criterios que la selección del visor Qt."""
    derot = page.derotation_matrix if reads_unrotated(page, bool(ocr_words)) else None
    layer = TextLayer()
    parts: list[str] = []
    last: fitz.Rect | None = None
    last_line = None
    for rect, text, word_start, line in page_words(page, ocr_words):
        text = str(text).strip()
        if not text:
            continue
        ur = fitz.Rect(rect) * derot if derot is not None else rect  # en el sentido de lectura
        if last is None:
            sep = ""
        elif line != last_line:
            sep = "\n"
        elif word_start or ur.x0 - last.x1 > max(2.5, (last.y1 - last.y0) * 0.15):
            sep = " "
        else:
            sep = ""
        layer.chars.append(text)
        layer.rects.append(fitz.Rect(rect))
        layer.seps.append(sep)
        parts += [sep, text]
        last, last_line = ur, line
    layer.text = "".join(parts)
    return layer


def words_text(words: list[tuple], page_width: float) -> str:
    """Texto de unas palabras de OCR sueltas (``(x0, y0, x1, y1, texto)``, p. ej. de un
    recorte) en orden de lectura: espacios entre palabras y un salto por línea."""
    items = [(rect, text, True) for rect, text in map(_ocr_word, words) if text]
    lines: list[list[str]] = []
    last_line = None
    for _rect, text, _start, line in sort_words_clustered(items, page_width):
        if line != last_line:
            lines.append([])
            last_line = line
        lines[-1].append(text)
    return "\n".join(" ".join(line) for line in lines)
