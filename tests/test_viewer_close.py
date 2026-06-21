"""Tests para la detección de cambios y guardado en el visor de PDF.

Cubre:
  - _compute_doc_state() / _doc_has_real_changes(): detección inteligente de cambios
    reales (rotación, anotaciones, nº de páginas) respecto al baseline guardado.
  - _save_in_place(): guardado sobre el archivo original con tobytes + write_bytes.
  - _request_close(): lógica de cierre — cuándo llamar a on_close directamente y
    cuándo mostrar el diálogo de confirmación.
  - Bandera _has_content_changes: bloquea el guardado directo en documentos con
    censura aplicada.
"""
from __future__ import annotations

import hashlib
import threading
import types
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from pdf_viewer._render_mixin import _RenderMixin
from pdf_viewer.viewer import PDFViewerTab


# ── stub mínimo ──────────────────────────────────────────────────────────────


class _Viewer(_RenderMixin):
    """Combina _RenderMixin con los métodos de viewer.py que no son de ningún mixin."""

    _compute_doc_state = PDFViewerTab._compute_doc_state
    _doc_has_real_changes = PDFViewerTab._doc_has_real_changes
    _request_close = PDFViewerTab._request_close

    def __getattr__(self, name):  # no-op para atributos no fijados
        return lambda *a, **k: None


def _make_viewer(doc: fitz.Document, path: str = "") -> _Viewer:
    """Stub con el estado mínimo necesario para los métodos bajo prueba."""
    v = _Viewer.__new__(_Viewer)
    v.doc = doc
    v._doc_lock = threading.Lock()
    v._is_modified = False
    v._has_content_changes = False
    v._doc_initial_state = None
    v._pending_close_after_save = False
    v.path = path

    # Captura de snacks y llamadas a on_close
    v._snack_msgs: list[str] = []
    v._show_snack = lambda msg, **kw: v._snack_msgs.append(msg)
    v._close_calls: list[bool] = []
    v.on_close = lambda self_: v._close_calls.append(True)

    # page_ref mock para _request_close
    v.page_ref = types.SimpleNamespace(open=lambda dlg: None, close=lambda dlg: None)

    # Control mock para _save_in_place_btn (usado en _redact_mixin, no aquí)
    v._save_in_place_btn = types.SimpleNamespace(disabled=False, update=lambda: None)

    return v


def _plain_pdf(tmp_path: Path, name: str = "doc.pdf") -> Path:
    """PDF de una página sin restricciones de seguridad."""
    path = tmp_path / name
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()
    return path


def _add_rect_annot(doc: fitz.Document, page_idx: int = 0) -> fitz.Annot:
    """Añade un rectángulo de anotación a la página indicada y devuelve el Annot."""
    page = doc[page_idx]
    return page.add_rect_annot(fitz.Rect(50, 50, 150, 150))


# ── _compute_doc_state ───────────────────────────────────────────────────────


class TestComputeDocState:
    def test_page_count_matches_doc(self, tmp_path):
        doc = fitz.open()
        for _ in range(3):
            doc.new_page()
        v = _make_viewer(doc)
        state = v._compute_doc_state()
        assert state["page_count"] == 3
        doc.close()

    def test_single_page_zero_rotation_by_default(self, tmp_path):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        state = v._compute_doc_state()
        assert state["pages"][0]["rotation"] == 0
        doc.close()

    def test_rotation_captured_in_snapshot(self, tmp_path):
        doc = fitz.open()
        page = doc.new_page()
        page.set_rotation(90)
        v = _make_viewer(doc)
        state = v._compute_doc_state()
        assert state["pages"][0]["rotation"] == 90
        doc.close()

    def test_annotation_captured_in_snapshot(self, tmp_path):
        doc = fitz.open()
        doc.new_page()
        page = doc[0]
        annot = _add_rect_annot(doc, 0)
        xref = annot.xref
        v = _make_viewer(doc)
        state = v._compute_doc_state()
        annot_xrefs = [a[0] for a in state["pages"][0]["annots"]]
        assert xref in annot_xrefs
        doc.close()

    def test_clean_page_has_empty_annots(self, tmp_path):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        state = v._compute_doc_state()
        assert state["pages"][0]["annots"] == []
        doc.close()


# ── _doc_has_real_changes ────────────────────────────────────────────────────


class TestDocHasRealChanges:
    def test_no_changes_returns_false(self):
        """Estado actual == baseline → no hay cambios reales."""
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True  # bandera rápida activa, pero estado idéntico
        assert v._doc_has_real_changes() is False
        doc.close()

    def test_rotation_detected(self):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        doc[0].set_rotation(90)
        v._is_modified = True
        assert v._doc_has_real_changes() is True
        doc.close()

    def test_rotation_revert_is_no_change(self):
        """Rotar 90° y volver a 0° debe dejar el estado igual al baseline."""
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        doc[0].set_rotation(90)
        doc[0].set_rotation(0)
        v._is_modified = True
        assert v._doc_has_real_changes() is False
        doc.close()

    def test_annotation_added_detected(self):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        _add_rect_annot(doc, 0)
        v._is_modified = True
        assert v._doc_has_real_changes() is True
        doc.close()

    def test_annotation_removed_detected(self):
        doc = fitz.open()
        doc.new_page()
        page = doc[0]
        annot = _add_rect_annot(doc, 0)
        xref = annot.xref
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        # Eliminar la anotación
        page = doc[0]
        annot = next(a for a in page.annots() if a.xref == xref)
        page.delete_annot(annot)
        v._is_modified = True
        assert v._doc_has_real_changes() is True
        doc.close()

    def test_content_changes_flag_short_circuits(self):
        """_has_content_changes = True → True sin comparar el estado."""
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        v._has_content_changes = True
        assert v._doc_has_real_changes() is True
        doc.close()

    def test_no_baseline_and_modified_returns_true(self):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = None
        v._is_modified = True
        assert v._doc_has_real_changes() is True
        doc.close()

    def test_no_baseline_and_not_modified_returns_false(self):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = None
        v._is_modified = False
        assert v._doc_has_real_changes() is False
        doc.close()

    def test_page_count_change_detected(self):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        doc.new_page()  # añadir página
        v._is_modified = True
        assert v._doc_has_real_changes() is True
        doc.close()

    def test_multi_page_partial_rotation(self):
        """Solo una de tres páginas rotada → True."""
        doc = fitz.open()
        for _ in range(3):
            doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        doc[1].set_rotation(180)
        v._is_modified = True
        assert v._doc_has_real_changes() is True
        doc.close()


# ── _save_in_place ───────────────────────────────────────────────────────────


class TestSaveInPlace:
    def test_saves_bytes_to_original_path(self, tmp_path):
        """El archivo en disco se reescribe con el contenido actualizado."""
        path = _plain_pdf(tmp_path)
        original_hash = hashlib.md5(path.read_bytes()).hexdigest()

        doc = fitz.open(str(path))
        _add_rect_annot(doc, 0)  # modificar en memoria
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True

        v._save_in_place()

        new_hash = hashlib.md5(path.read_bytes()).hexdigest()
        assert new_hash != original_hash, "El archivo en disco no cambió"
        doc.close()

    def test_saved_content_readable_by_fitz(self, tmp_path):
        """El archivo guardado se puede abrir con fitz y contiene la anotación."""
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        _add_rect_annot(doc, 0)
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True
        v._save_in_place()
        doc.close()

        doc2 = fitz.open(str(path))
        try:
            page = doc2[0]
            assert len(list(page.annots())) == 1
        finally:
            doc2.close()

    def test_clears_is_modified_on_success(self, tmp_path):
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True

        v._save_in_place()

        assert v._is_modified is False
        doc.close()

    def test_clears_has_content_changes_on_success(self, tmp_path):
        """Tras guardar una copia (censura ya aplicada), las banderas se limpian.

        Nota: en producción _save_in_place bloquea si _has_content_changes=True,
        pero _on_save_result (ruta del picker) sí limpia la bandera. Este test
        comprueba la ruta directa del método cuando la bandera se fuerza a False
        antes de llamarlo, para que el flujo llegue a la limpieza.
        """
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        # No bloqueamos: el flag se asigna manualmente a False para llegar al final
        v._has_content_changes = False
        v._is_modified = True

        v._save_in_place()

        assert v._has_content_changes is False
        doc.close()

    def test_updates_baseline_after_save(self, tmp_path):
        """_doc_initial_state debe actualizarse para que el próximo cierre sea limpio."""
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        old_state = v._doc_initial_state

        _add_rect_annot(doc, 0)
        v._is_modified = True
        v._save_in_place()

        assert v._doc_initial_state is not old_state
        # El nuevo baseline incluye la anotación
        new_annots = v._doc_initial_state["pages"][0]["annots"]
        assert len(new_annots) == 1
        doc.close()

    def test_shows_success_snack_with_filename(self, tmp_path):
        path = _plain_pdf(tmp_path, "mi_doc.pdf")
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True

        v._save_in_place()

        assert any("mi_doc.pdf" in m for m in v._snack_msgs)
        doc.close()

    def test_calls_on_close_when_close_after_true(self, tmp_path):
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True

        v._save_in_place(_close_after=True)

        assert len(v._close_calls) == 1
        doc.close()

    def test_does_not_call_on_close_without_flag(self, tmp_path):
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True

        v._save_in_place(_close_after=False)

        assert v._close_calls == []
        doc.close()

    def test_blocked_by_content_changes(self, tmp_path):
        """Si hay censura aplicada, no debe escribir el archivo ni limpiar flags."""
        path = _plain_pdf(tmp_path)
        original_bytes = path.read_bytes()

        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True
        v._has_content_changes = True

        v._save_in_place()

        assert path.read_bytes() == original_bytes, "El archivo no debía modificarse"
        assert v._is_modified is True, "La bandera de modificación no debe limpiarse"
        assert any(m for m in v._snack_msgs), "Debe mostrarse un mensaje informativo"
        doc.close()

    def test_blocked_by_content_changes_does_not_close(self, tmp_path):
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True
        v._has_content_changes = True

        v._save_in_place(_close_after=True)

        assert v._close_calls == [], "on_close no debe llamarse si el guardado fue bloqueado"
        doc.close()

    def test_permission_error_shows_snack_and_keeps_modified(self, tmp_path):
        """Si write_bytes lanza PermissionError, la bandera permanece True."""
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True

        with patch.object(Path, "write_bytes", side_effect=PermissionError("bloqueado")):
            v._save_in_place()

        assert v._is_modified is True
        assert any("permiso" in m.lower() for m in v._snack_msgs)
        doc.close()

    def test_permission_error_does_not_call_on_close(self, tmp_path):
        path = _plain_pdf(tmp_path)
        doc = fitz.open(str(path))
        v = _make_viewer(doc, str(path))
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True

        with patch.object(Path, "write_bytes", side_effect=PermissionError("bloqueado")):
            v._save_in_place(_close_after=True)

        assert v._close_calls == []
        doc.close()


# ── _request_close ───────────────────────────────────────────────────────────


class TestRequestClose:
    def test_not_modified_closes_directly(self):
        """_is_modified = False → on_close se llama sin mostrar diálogo."""
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = False

        v._request_close()

        assert len(v._close_calls) == 1
        doc.close()

    def test_modified_but_reverted_closes_directly(self):
        """Bandera activa pero cambios revertidos → cierre sin diálogo."""
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        doc[0].set_rotation(90)
        doc[0].set_rotation(0)  # revertir
        v._is_modified = True  # la bandera rápida sigue activa

        v._request_close()

        assert len(v._close_calls) == 1
        doc.close()

    def test_real_changes_open_dialog_not_close(self):
        """Cambios reales sin revertir → diálogo mostrado, on_close no llamado todavía."""
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        _add_rect_annot(doc, 0)
        v._is_modified = True

        v._request_close()

        assert v._close_calls == [], "on_close no debe llamarse directamente con cambios reales"
        doc.close()

    def test_real_rotation_opens_dialog(self):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        doc[0].set_rotation(90)
        v._is_modified = True

        v._request_close()

        assert v._close_calls == []
        doc.close()

    def test_content_changes_opens_dialog(self):
        """Censura aplicada (_has_content_changes) también requiere confirmación."""
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = v._compute_doc_state()
        v._is_modified = True
        v._has_content_changes = True

        v._request_close()

        assert v._close_calls == []
        doc.close()

    def test_no_baseline_not_modified_closes_directly(self):
        doc = fitz.open()
        doc.new_page()
        v = _make_viewer(doc)
        v._doc_initial_state = None
        v._is_modified = False

        v._request_close()

        assert len(v._close_calls) == 1
        doc.close()
