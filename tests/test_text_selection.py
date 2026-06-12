"""Tests del subsistema de selección de texto (`_TextSelMixin`).

Fijan el contrato eficiente para páginas OCR:
- ``_get_page_words`` produce UNA tupla por palabra OCR detectada (no por
  carácter sintético) con ``word_start=True`` y orden de lectura por clustering
  de renglones.
- La reconstrucción de texto inserta espacios entre palabras OCR (sus cajas se
  tocan) y saltos de línea entre renglones.
- ``compute_text=False`` (arrastre en vivo) omite la reconstrucción del string
  y NO redibuja el overlay de una página si el barrido no cambió de palabra
  (firma ``_text_sel_sig``).

Se ejercita sobre un stub liviano con los métodos reales del mixin enlazados,
igual que en test_text_cache_prune.py, con un ``fitz.Document`` real en memoria.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import fitz
import pytest

from pdf_viewer._text_sel_mixin import _TextSelMixin


class _FakeLayer:
    """Capa de overlay mínima: sólo controls/visible/update()."""

    def __init__(self) -> None:
        self.controls: list = []
        self.visible = False

    def update(self) -> None:
        pass


def _det(text: str, x0: float, y0: float, x1: float, y1: float) -> SimpleNamespace:
    return SimpleNamespace(text=text, bbox=fitz.Rect(x0, y0, x1, y1), score=0.9)


class _Stub:
    """Atributos mínimos que tocan los métodos bajo prueba."""

    # Métodos reales del mixin.
    _get_page_words        = _TextSelMixin._get_page_words
    _reading_frames        = _TextSelMixin._reading_frames
    _is_ocr_page           = _TextSelMixin._is_ocr_page
    _nearest_word_index    = _TextSelMixin._nearest_word_index
    _words_in_sweep        = _TextSelMixin._words_in_sweep
    _update_text_selection = _TextSelMixin._update_text_selection

    def __init__(self, doc: fitz.Document, detections_by_page: dict[int, list]) -> None:
        self.doc = doc
        self._doc_lock = threading.Lock()
        self._page_words: dict[int, list] = {}
        self._page_word_bands: dict[int, dict] = {}
        self._ocr_by_page = {
            pn: SimpleNamespace(detections=dets)
            for pn, dets in detections_by_page.items()
        }
        self.zoom = 1.0
        self._text_sel_layers = [_FakeLayer() for _ in range(len(doc))]
        self._text_sel_sig: dict[int, tuple] = {}
        self._text_sel_active_pages: set[int] = set()
        self._text_sel_sel_rect = None
        self._text_sel_handle_start_disp = None
        self._text_sel_handle_end_disp = None
        self._text_sel_start_pn = None
        self._text_sel_end_pn = None


@pytest.fixture()
def ocr_doc():
    """Página en blanco (sin texto nativo) con dos renglones OCR simulados."""
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    dets = [
        # renglón 1 — cajas que se tocan (hueco 0, típico del OCR)
        _det("hola",  50, 100, 90, 112),
        _det("mundo", 90, 100, 140, 112),
        # renglón 2 — leve jitter vertical en y0
        _det("adios", 50, 130, 95, 142),
        _det("ya",    95, 131, 115, 143),
    ]
    stub = _Stub(doc, {0: dets})
    yield stub
    doc.close()


class TestOCRWordTuples:
    def test_one_tuple_per_ocr_word(self, ocr_doc):
        words = ocr_doc._get_page_words(0)
        assert len(words) == 4  # por palabra, NO por carácter
        assert [w[1] for w in words] == ["hola", "mundo", "adios", "ya"]

    def test_word_start_marks_every_ocr_word(self, ocr_doc):
        words = ocr_doc._get_page_words(0)
        assert all(w[2] is True for w in words)

    def test_line_indices_cluster_jittered_rows(self, ocr_doc):
        words = ocr_doc._get_page_words(0)
        # 4-tuplas (rect, texto, word_start, line_idx); el jitter de 1 pt en y0
        # no debe partir el renglón ni fundir renglones vecinos.
        lines = [w[3] for w in words]
        assert lines == [0, 0, 1, 1]

    def test_native_page_still_char_level(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "ab cd", fontsize=12)
        stub = _Stub(doc, {})
        try:
            words = stub._get_page_words(0)
            # rawdict char-level: 4 chars no-espacio; el espacio REAL del PDF
            # marca word_start=True en el char que le sigue ("c").
            assert [w[1] for w in words] == ["a", "b", "c", "d"]
            assert [bool(w[2]) for w in words] == [False, False, True, False]
        finally:
            doc.close()

    def test_native_copy_keeps_spaces_even_without_glyph_gap(self):
        """La copia de texto nativo conserva los espacios vía la marca
        word_start (espacio real del PDF), sin depender del hueco geométrico
        entre cajas — que en PDFs buscables es ≈0 y daba "FORMATOUNICO…"."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "FORMATO UNICO PARA", fontsize=12)
        stub = _Stub(doc, {})
        try:
            words = stub._get_page_words(0)
            # Simular capa buscable: cajas estiradas que se tocan (hueco 0).
            for i in range(1, len(words)):
                prev, cur = words[i - 1][0], words[i][0]
                if cur.x0 > prev.x1:
                    prev.x1 = cur.x0
            first, last = words[0][0], words[-1][0]
            text = stub._update_text_selection(
                0, ((first.x0 + first.x1) / 2, (first.y0 + first.y1) / 2),
                0, ((last.x0 + last.x1) / 2, (last.y0 + last.y1) / 2),
                update_ui=False,
            )
            assert text == "FORMATO UNICO PARA"
        finally:
            doc.close()


class TestStreamOrderWithOverlappingBoxes:
    def test_overlapping_word_boxes_keep_stream_order(self):
        """Capa "buscable": las cajas de palabras vecinas se solapan en X (la
        'S' final de GASTOS empieza después de la 'D' de DE). Ordenar char a
        char por x0 entrelazaba las letras ("GASTODSE"); con grupos de palabra
        del stream el orden se conserva."""
        from pdf_viewer._text_sel_mixin import _sort_words_clustered

        def cw(ch, x0, x1, ws=False):
            return (fitz.Rect(x0, 100, x1, 112), ch, ws)

        words = [
            cw("G", 0, 10), cw("A", 10, 20), cw("S", 20, 30), cw("T", 30, 40),
            cw("O", 40, 50), cw("S", 58, 68),           # solapa con "DE"
            cw("D", 52, 62, ws=True), cw("E", 62, 72),
        ]
        gids = [1, 1, 1, 1, 1, 1, 2, 2]
        out = _sort_words_clustered(words, 595, groups=gids)
        assert "".join(w[1] for w in out) == "GASTOSDE"

    def test_column_aware_sorter_also_group_ordered(self):
        from pdf_viewer._text_sel_mixin import _sort_words_column_aware

        def cw(ch, x0, x1, ws=False):
            return (fitz.Rect(x0, 100, x1, 112), ch, ws)

        words = [
            cw("A", 0, 12), cw("B", 18, 30),            # palabra 1 ("AB")
            cw("C", 26, 38, ws=True), cw("D", 38, 50),  # palabra 2, B solapa C
        ]
        gids = [1, 1, 2, 2]
        out = _sort_words_column_aware(words, 595, groups=gids)
        assert "".join(w[1] for w in out) == "ABCD"


class TestOCRTextReconstruction:
    def test_spaces_between_words_and_newline_between_lines(self, ocr_doc):
        text = ocr_doc._update_text_selection(
            0, (51, 106), 0, (114, 137), update_ui=False,
        )
        assert text == "hola mundo\nadios ya"

    def test_word_sweep_subset(self, ocr_doc):
        # Barrido sólo sobre el primer renglón.
        text = ocr_doc._update_text_selection(
            0, (51, 106), 0, (139, 106), update_ui=False,
        )
        assert text == "hola mundo"


class TestLineSegmentSplitting:
    def test_big_gap_splits_highlight_stripes(self):
        """Fila de formulario: dos campos en el mismo renglón separados por un
        hueco grande → DOS franjas de selección, no una banda continua que
        pinte el espacio vacío (mismo umbral 2×alto que _line_merged_rects)."""
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        dets = [
            _det("Tel.",  50, 100, 90, 112),
            _det("Fecha", 400, 100, 450, 112),   # hueco de 310 pt >> 2×12
        ]
        stub = _Stub(doc, {0: dets})
        try:
            stub._update_text_selection(0, (51, 106), 0, (449, 106), update_ui=False)
            layer = stub._text_sel_layers[0]
            # 2 franjas + 2 handles (página inicio y fin de la selección)
            assert len(layer.controls) == 4
        finally:
            doc.close()

    def test_touching_words_stay_one_stripe(self, ocr_doc):
        ocr_doc._update_text_selection(0, (51, 106), 0, (139, 106), update_ui=False)
        layer = ocr_doc._text_sel_layers[0]
        # cajas que se tocan → una sola franja (+2 handles)
        assert len(layer.controls) == 3


class TestHybridDedupe:
    def test_ocr_detection_covered_by_native_text_is_dropped(self):
        """Página híbrida: el OCR re-detecta texto que ya existe como capa
        nativa → la detección duplicada se descarta (el nativo es exacto).
        Una detección fuera de la zona nativa se conserva."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Factura", fontsize=12)
        # bbox real de la palabra nativa según PyMuPDF
        nx0, ny0, nx1, ny1, *_ = page.get_text("words")[0]
        dets = [
            _det("Factura", nx0, ny0, nx1, ny1),     # duplicado del nativo
            _det("escaneo", 300, 500, 360, 512),      # región sin texto nativo
        ]
        stub = _Stub(doc, {0: dets})
        try:
            words = stub._get_page_words(0)
            texts = [w[1] for w in words]
            # chars nativos de "Factura" + la palabra OCR no cubierta
            assert "escaneo" in texts
            assert "Factura" not in texts          # la det duplicada no entra
            assert "".join(t for t in texts if len(t) == 1) == "Factura"
        finally:
            doc.close()

    def test_pure_ocr_detections_unaffected(self, ocr_doc):
        # Sin texto nativo no hay nada que cubra: las 4 detecciones entran.
        assert len(ocr_doc._get_page_words(0)) == 4

    def test_det_bleeding_into_next_line_does_not_squash_it(self):
        """Las cajas OCR vienen dilatadas y rozan la fila vecina: ese roce NO
        debe clampear los chars de la otra fila a una astilla (renglones que
        quedaban sin franja de selección visible)."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Primera", fontsize=12)
        page.insert_text((72, 114), "Segunda", fontsize=12)
        w1 = page.get_text("words")[0]
        w2 = page.get_text("words")[1]
        # det duplicado de "Primera" cuyo bbox invade 2 pt la fila de "Segunda"
        det = _det("Primera", w1[0], w1[1], w1[2], w2[1] + 2.0)
        stub = _Stub(doc, {0: [det]})
        try:
            words = stub._get_page_words(0)
            seg_chars = [w for w in words if w[1] in "Segunda"]
            assert seg_chars
            min_h = min(r.y1 - r.y0 for r, *_ in seg_chars)
            # la fila vecina conserva una altura razonable (no una astilla)
            assert min_h > (w2[3] - w2[1]) * 0.4
        finally:
            doc.close()

    def test_native_boxes_trimmed_to_ocr_ink(self):
        """PDF "buscable": la caja nativa (métrica de fuente) es más alta que la
        tinta del escaneo. Al descartar la detección OCR duplicada, su rango Y
        (ajustado al píxel) recorta las cajas nativas → la franja de selección
        abraza el texto visible."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Factura", fontsize=12)
        nx0, ny0, nx1, ny1, *_ = page.get_text("words")[0]
        # det más "apretada" verticalmente que la caja nativa (como la tinta)
        det = _det("Factura", nx0, ny0 + 2.5, nx1, ny1 - 2.5)
        stub = _Stub(doc, {0: [det]})
        try:
            words = stub._get_page_words(0)
            chars = [w for w in words if len(w[1]) == 1]
            assert chars, "los chars nativos deben seguir presentes"
            for r, *_rest in chars:
                assert r.y0 >= det.bbox.y0 - 1e-6
                assert r.y1 <= det.bbox.y1 + 1e-6
        finally:
            doc.close()


class TestSegmentHeights:
    def test_stripe_height_is_per_segment_not_per_line(self):
        """Una caja con jitter/más alta sólo engorda SU tramo: la franja del
        otro campo de la fila conserva la altura de su propia caja."""
        from pdf_viewer.renderer import BASE_SCALE

        doc = fitz.open()
        doc.new_page(width=595, height=842)
        dets = [
            _det("bajo", 50, 100, 90, 112),     # alto 12
            _det("alto", 400, 96, 450, 118),    # alto 22, mismo renglón
        ]
        stub = _Stub(doc, {0: dets})
        try:
            stub._update_text_selection(0, (51, 106), 0, (449, 106), update_ui=False)
            layer = stub._text_sel_layers[0]
            stripes = [c for c in layer.controls if c.bgcolor == "#5500AAFF"]
            assert len(stripes) == 2
            heights = sorted(c.height for c in stripes)
            assert heights[0] == pytest.approx(12 * BASE_SCALE)
            assert heights[1] == pytest.approx(22 * BASE_SCALE)
        finally:
            doc.close()


class TestDragFastPath:
    def test_compute_text_false_builds_overlay_without_text(self, ocr_doc):
        text = ocr_doc._update_text_selection(
            0, (51, 106), 0, (114, 137), update_ui=False, compute_text=False,
        )
        assert text == ""                       # string omitido en el drag
        layer = ocr_doc._text_sel_layers[0]
        assert layer.controls and layer.visible  # pero el resaltado sí se dibuja
        assert 0 in ocr_doc._text_sel_sig

    def test_unchanged_sweep_skips_rebuild(self, ocr_doc):
        ocr_doc._update_text_selection(
            0, (51, 106), 0, (114, 137), update_ui=False, compute_text=False,
        )
        layer = ocr_doc._text_sel_layers[0]
        first_controls = layer.controls
        # Mismo barrido a nivel de palabra (puntos distintos dentro de las
        # mismas palabras extremas) → no debe reconstruirse la lista de cajas.
        ocr_doc._update_text_selection(
            0, (60, 105), 0, (110, 138), update_ui=False, compute_text=False,
        )
        assert layer.controls is first_controls

    def test_full_call_always_rebuilds_and_returns_text(self, ocr_doc):
        ocr_doc._update_text_selection(
            0, (51, 106), 0, (114, 137), update_ui=False, compute_text=False,
        )
        layer = ocr_doc._text_sel_layers[0]
        first_controls = layer.controls
        # Al soltar (compute_text=True) se recalcula todo: texto y overlay.
        text = ocr_doc._update_text_selection(
            0, (51, 106), 0, (114, 137), update_ui=False,
        )
        assert text == "hola mundo\nadios ya"
        assert layer.controls is not first_controls

    def test_changed_sweep_rebuilds(self, ocr_doc):
        ocr_doc._update_text_selection(
            0, (51, 106), 0, (114, 137), update_ui=False, compute_text=False,
        )
        layer = ocr_doc._text_sel_layers[0]
        first_controls = layer.controls
        # Encoger el barrido al primer renglón cambia (si, ei) → rebuild.
        ocr_doc._update_text_selection(
            0, (51, 106), 0, (139, 106), update_ui=False, compute_text=False,
        )
        assert layer.controls is not first_controls
