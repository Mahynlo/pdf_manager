"""Texto de una página en orden de lectura.

Trabaja con el texto de una página (:class:`pdf_core.pdf.PageText`), que lee Python de un PDF o
da el visor con su motor. ``page_words`` toma sus caracteres (y las palabras de OCR que no
tapen texto nativo) ordenados por columnas y líneas. ``TextLayer`` añade el separador que va
delante de cada carácter (``""``, espacio o salto de línea) y el texto completo, que usan el
asistente IA y el panel de OCR (la selección y la búsqueda del visor son de EmbedPDF).

Las palabras de OCR las escribe el visor en su documento como texto invisible, para que
EmbedPDF las seleccione como texto nativo (``app/ui/src/lib/pdf-engine/page-ocr.ts``).

Las coordenadas son las de la página tal como se ve (ya girada), en puntos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pdf_core.pdf import PageText, Rect
from pdf_core.reading_order import (
    assign_line_indices,
    sort_words_clustered,
    sort_words_column_aware,
)

Word = tuple  # (Rect, texto, inicio_de_palabra, línea)


def reads_unrotated(page: PageText, has_ocr: bool) -> bool:
    """True si el orden de lectura se calcula sobre la página sin girar.

    El texto nativo de una página girada se lee en su orientación original; las
    palabras de OCR ya vienen en la orientación en que se ve la página.
    """
    return bool(page.rotation) and not has_ocr


def _ocr_word(word: tuple) -> tuple[Rect, str]:
    if isinstance(word[0], (int, float)):
        return Rect(word[0], word[1], word[2], word[3]), str(word[4]).strip()
    return Rect(*word[0]), str(word[1]).strip()


def _coverage(native: list[Rect]):
    """Función que dice si un rectángulo queda tapado (40 % o más) por los de ``native``."""
    native_bands: dict[int, list[Rect]] = {}
    for r in native:
        for bi in range(int(r.y0 // 10), int(r.y1 // 10) + 1):
            native_bands.setdefault(bi, []).append(r)

    def covered_by_native(rect: Rect) -> bool:
        area = rect.area
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


def page_words(page: PageText, ocr_words: list[tuple] | None = None) -> list[Word]:
    """Caracteres de la página (más palabras de OCR) en orden de lectura.

    Cada elemento es ``(rect, texto, inicio_de_palabra, línea)``; ``rect`` está en
    coordenadas de la página girada.
    """
    page_width = page.rect.width

    words: list[tuple] = []
    gids: list[int] = []
    gid = 0
    last_line = None
    pending_space = False
    for char in page.chars:
        if char.line != last_line:
            gid += 1
            last_line = char.line
            pending_space = False
        if not char.text.strip():
            pending_space = True
            continue
        if pending_space:
            gid += 1
        words.append((page.to_view(char.box), char.text, pending_space))
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

    if reads_unrotated(page, bool(ocr_words)):
        sort_w = page.rect.height if page.rotation in (90, 270) else page_width
        words = sort_words_column_aware(words, sort_w, pos=page.to_page, groups=gids)
        return assign_line_indices(words, pos=page.to_page)
    if ocr_words:
        return sort_words_clustered(words, page_width, groups=gids)
    words = sort_words_column_aware(words, page_width, groups=gids)
    return assign_line_indices(words)


@dataclass
class TextLayer:
    """Texto seleccionable de una página: un elemento por carácter (o palabra de OCR)."""

    chars: list[str] = field(default_factory=list)
    rects: list[Rect] = field(default_factory=list)
    seps: list[str] = field(default_factory=list)  # separador delante de cada carácter
    text: str = ""  # "".join(sep + carácter)


def build_text_layer(page: PageText, ocr_words: list[tuple] | None = None) -> TextLayer:
    """Capa de texto de ``page``, en orden de lectura."""
    unrotated = reads_unrotated(page, bool(ocr_words))
    layer = TextLayer()
    parts: list[str] = []
    last: Rect | None = None
    last_line = None
    for rect, text, word_start, line in page_words(page, ocr_words):
        text = str(text).strip()
        if not text:
            continue
        ur = page.to_page(rect) if unrotated else rect  # en el sentido de lectura
        if last is None:
            sep = ""
        elif line != last_line:
            sep = "\n"
        elif word_start or ur.x0 - last.x1 > max(2.5, (last.y1 - last.y0) * 0.15):
            sep = " "
        else:
            sep = ""
        layer.chars.append(text)
        layer.rects.append(Rect(*rect))
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
