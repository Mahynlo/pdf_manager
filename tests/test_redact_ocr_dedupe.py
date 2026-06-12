"""Dedupe de coincidencias de censura en PDFs híbridos/buscables.

Cuando la misma palabra existe en la capa de texto nativo Y como detección OCR
(escaneo + capa invisible, o página híbrida re-OCReada), `_find_term_matches`
generaba DOS coincidencias por hit: el rect nativo (métrica de fuente, más
alto) y el rect OCR (ajustado al píxel) → doble recuadro en el preview y doble
censura aplicada. El hit OCR que solapa ≥50% con uno nativo debe descartarse;
los hits OCR en regiones sin texto nativo se conservan.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import fitz
import pytest

from pdf_viewer._redact_mixin import _RedactMixin


def _det(text: str, x0: float, y0: float, x1: float, y1: float) -> SimpleNamespace:
    return SimpleNamespace(text=text, bbox=fitz.Rect(x0, y0, x1, y1), score=0.9)


class _Stub:
    _find_term_matches    = _RedactMixin._find_term_matches
    _search_phrase        = _RedactMixin._search_phrase
    _search_phrase_in_ocr = _RedactMixin._search_phrase_in_ocr
    _REDACT_MAX_MATCHES   = 500

    def __init__(self, doc: fitz.Document, detections_by_page: dict[int, list]) -> None:
        self.doc = doc
        self._doc_lock = threading.Lock()
        self._redact_incl_ocr = SimpleNamespace(value=True)
        self._ocr_by_page = {
            pn: SimpleNamespace(detections=dets)
            for pn, dets in detections_by_page.items()
        }


class TestRedactOCRDedupe:
    def test_ocr_hit_overlapping_native_hit_is_dropped(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Secreto", fontsize=12)
        nx0, ny0, nx1, ny1, *_ = page.get_text("words")[0]
        stub = _Stub(doc, {0: [_det("Secreto", nx0, ny0, nx1, ny1)]})
        try:
            matches = stub._find_term_matches("Secreto", case_sensitive=True)
            # un solo recuadro: el nativo; el hit OCR duplicado se descarta
            assert len(matches) == 1
        finally:
            doc.close()

    def test_kept_match_adopts_tight_ocr_geometry(self):
        """El hit único conserva la caja OCR (tinta), no la métrica de fuente:
        el recuadro de censura por búsqueda debe verse igual de ajustado que
        uno manual."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Secreto", fontsize=12)
        nx0, ny0, nx1, ny1, *_ = page.get_text("words")[0]
        det = _det("Secreto", nx0 + 1, ny0 + 3, nx1 - 1, ny1 - 3)  # más apretada
        stub = _Stub(doc, {0: [det]})
        try:
            matches = stub._find_term_matches("Secreto", case_sensitive=True)
            assert len(matches) == 1
            _, rect, _ = matches[0]
            assert rect.y0 == pytest.approx(det.bbox.y0)
            assert rect.y1 == pytest.approx(det.bbox.y1)
            assert rect.x0 == pytest.approx(det.bbox.x0)
            assert rect.x1 == pytest.approx(det.bbox.x1)
        finally:
            doc.close()

    def test_ocr_hit_in_scanned_region_is_kept(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Secreto", fontsize=12)
        nx0, ny0, nx1, ny1, *_ = page.get_text("words")[0]
        dets = [
            _det("Secreto", nx0, ny0, nx1, ny1),   # duplicado del nativo
            _det("Secreto", 300, 500, 350, 512),    # región puramente escaneada
        ]
        stub = _Stub(doc, {0: dets})
        try:
            matches = stub._find_term_matches("Secreto", case_sensitive=True)
            assert len(matches) == 2  # nativo + el OCR no duplicado
        finally:
            doc.close()

    def test_pure_ocr_page_matches_unaffected(self):
        doc = fitz.open()
        doc.new_page(width=595, height=842)  # página sin texto nativo
        stub = _Stub(doc, {0: [_det("Secreto", 100, 100, 150, 112)]})
        try:
            matches = stub._find_term_matches("Secreto", case_sensitive=True)
            assert len(matches) == 1
        finally:
            doc.close()


class TestNativePhraseSearch:
    """Búsqueda de censura sobre texto nativo: palabra, frase y palabra completa."""

    def _page(self, *lines: str):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        for i, ln in enumerate(lines):
            page.insert_text((72, 100 + i * 14), ln, fontsize=11)
        return doc, page

    def test_single_word_whole_word_only(self):
        """"la" NO debe coincidir dentro de "tabla" (siempre palabra completa)."""
        doc, page = self._page("la tabla grande")
        stub = _Stub(doc, {})
        try:
            matches = stub._find_term_matches("la", case_sensitive=True)
            assert len(matches) == 1
        finally:
            doc.close()

    def test_phrase_same_line_single_rect(self):
        doc, page = self._page("uno dos tres")
        stub = _Stub(doc, {})
        try:
            rects = stub._search_phrase(page, "uno dos", True, whole_word=True)
            assert len(rects) == 1
        finally:
            doc.close()

    def test_phrase_wrapping_lines_gives_one_rect_per_line(self):
        """Frase que cruza de renglón: un rect por línea, no un bloque gigante
        que abarque todo el ancho entre ambas líneas."""
        doc, page = self._page("uno dos", "tres cuatro")
        stub = _Stub(doc, {})
        try:
            rects = stub._search_phrase(page, "dos tres", True, whole_word=True)
            assert len(rects) == 2
            for r in rects:
                assert r.height < 20  # altura de UNA línea, no de las dos

            # y cada rect cubre solo su palabra, no el renglón completo
            w_uno = page.get_text("words")[0]
            assert all(r.x0 > w_uno[2] - 1 for r in rects if abs(r.y0 - w_uno[1]) < 5)
        finally:
            doc.close()

    def test_accent_folding_case_insensitive(self):
        doc, page = self._page("Comisión Federal")
        stub = _Stub(doc, {})
        try:
            matches = stub._find_term_matches("comision", case_sensitive=False)
            assert len(matches) == 1
        finally:
            doc.close()


class TestOCRPhraseSearch:
    """Búsqueda de censura sobre detecciones OCR (una det por palabra)."""

    def test_phrase_across_detections_same_line(self):
        stub = _Stub(fitz.open(), {})
        dets = [
            _det("hola",  50, 100, 90, 112),
            _det("mundo", 95, 100, 140, 112),
        ]
        results = stub._search_phrase_in_ocr(dets, "hola mundo", True, whole_word=True)
        assert len(results) == 1
        rect, label = results[0]
        assert rect.x0 == 50 and rect.x1 == 140

    def test_phrase_wrapping_lines_gives_one_rect_per_line(self):
        stub = _Stub(fitz.open(), {})
        dets = [
            _det("gastos", 400, 100, 450, 112),   # fin del renglón 1
            _det("de",      50, 130,  70, 142),   # inicio del renglón 2
        ]
        results = stub._search_phrase_in_ocr(dets, "gastos de", True, whole_word=True)
        assert len(results) == 2
        for rect, _label in results:
            assert rect.height < 20

    def test_whole_word_does_not_match_inside_detection(self):
        stub = _Stub(fitz.open(), {})
        dets = [_det("tabla", 50, 100, 90, 112)]
        results = stub._search_phrase_in_ocr(dets, "la", True, whole_word=True)
        assert results == []

    def test_accent_folding_in_ocr(self):
        stub = _Stub(fitz.open(), {})
        dets = [_det("Comisión", 50, 100, 110, 112)]
        results = stub._search_phrase_in_ocr(dets, "Comision", True, whole_word=True)
        assert len(results) == 1
