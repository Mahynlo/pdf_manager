"""OCR en dos fases: ``prepare_page`` (bajo doc lock) + ``recognize_page`` (sin
lock).

El visor mantiene su ``_doc_lock`` solo durante la rasterización; la inferencia
(los segundos lentos) corre fuera, así el render/scroll no se bloquea durante
el OCR. ``process_page`` queda como conveniencia todo-en-uno (extractor por
lotes). Estos tests cubren la fase de preparación y el ensamblado del resultado
sin invocar el modelo (páginas nativas → sin regiones que inferir).
"""
from __future__ import annotations

import fitz

from pdf_viewer.ocr.processor import OCRProcessor, PreparedPage


def _processor() -> OCRProcessor:
    return OCRProcessor(workspace_root=".")


class TestPreparePage:
    def test_native_page_has_no_regions_without_force(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Texto nativo", fontsize=12)
        try:
            prep = _processor().prepare_page(doc, 0, force_ocr=False)
            assert prep.page_kind == "native"
            assert prep.regions == []          # nada que inferir
            assert len(prep.native_segments) == 1
        finally:
            doc.close()

    def test_force_ocr_rasterizes_regions(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Texto nativo", fontsize=12)
        try:
            prep = _processor().prepare_page(doc, 0, force_ocr=True)
            # sin bloques de imagen → fallback: la página completa como región
            assert len(prep.regions) == 1
            rect, scale, img = prep.regions[0]
            assert img.shape[0] > 0 and img.shape[1] > 0
        finally:
            doc.close()


class TestRecognizePage:
    def test_native_only_result_assembled_without_inference(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Texto nativo", fontsize=12)
        try:
            proc = _processor()
            prep = proc.prepare_page(doc, 0, force_ocr=False)
            result = proc.recognize_page(prep)   # sin regiones → no carga modelo
            assert result.mode_label == "Nativo"
            assert result.detections == []
            assert [s.text for s in result.segments] == ["Texto nativo"]
        finally:
            doc.close()

    def test_process_page_equals_two_phase(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "Texto nativo", fontsize=12)
        try:
            proc = _processor()
            one_shot = proc.process_page(doc, 0, force_ocr=False)
            two_phase = proc.recognize_page(proc.prepare_page(doc, 0, force_ocr=False))
            assert one_shot.mode_label == two_phase.mode_label
            assert [s.text for s in one_shot.segments] == [s.text for s in two_phase.segments]
        finally:
            doc.close()

    def test_regions_released_after_recognize(self):
        """Las imágenes rasterizadas se liberan al terminar la inferencia."""
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        try:
            proc = _processor()
            prep = proc.prepare_page(doc, 0, force_ocr=False)
            prep.regions.append((fitz.Rect(0, 0, 1, 1), 1.0,
                                 __import__("numpy").zeros((0, 0, 3), dtype="uint8")))
            proc.recognize_page(prep)
            assert prep.regions == []
        finally:
            doc.close()
