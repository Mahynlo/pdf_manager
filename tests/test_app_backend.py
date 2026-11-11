"""Backend de la app HTML (``app/backend``): RPC, servicio Combinar y coherencia con el frontend.

Se prueba sin ventana: los servicios solo dependen del protocolo ``Host``.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import numpy as np
import pypdfium2
import pytest
from pdfkit import (
    add_annot,
    add_image,
    add_page,
    add_text,
    annots,
    delete_annots,
    encrypted,
    pack_page_texts,
    page_texts,
    pdf_bytes,
    run_engine,
)

import app  # noqa: F401  (añade src/ al sys.path)
from app import UI_DIR
from app.backend.rpc import Registry, UserError, exposed
from app.backend.services import build_registry
from app.backend.services.ai import AiService
from app.backend.services.app_service import AppService
from app.backend.services.documents import DocumentService
from app.backend.services.extract import ExtractService
from app.backend.services.help import HelpService
from app.backend.services.merge import MergeService
from app.backend.services.ocr import OcrService
from app.backend.services.redact import RedactService
from app.backend.services.security import SecurityService
from app.backend.services.viewer import ViewerService
from app.backend.settings import Settings
from pdf_core.pdf import UNRESTRICTED, Document, PasswordError, Rect


class FakeHost:
    def __init__(self, picks: list[str] | None = None, save_to: str | None = None, folder: str | None = None) -> None:
        self.picks = picks or []
        self.save_to = save_to
        self.folder = folder
        self.saved_suggestions: list[str] = []
        self.events: list[tuple[str, object]] = []
        self.uploads: dict[str, bytes | None] = {}  # lo que el visor sube (upload_url)
        self.opened: list[str] = []

    def pick_pdfs(self) -> list[str]:
        return self.picks

    def pick_documents(self) -> list[str]:
        return self.picks

    def pick_pdf(self) -> str | None:
        return self.picks[0] if self.picks else None

    def pick_folder(self) -> str | None:
        return self.folder

    def pick_output_folder(self) -> str | None:
        return self.folder

    def save_pdf(self, suggested_path: str) -> str | None:
        self.saved_suggestions.append(suggested_path)
        return self.save_to

    def save_text(self, suggested_path: str) -> str | None:
        return self.save_pdf(suggested_path)

    def read_file(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def write_file(self, path: str, data: bytes) -> None:
        Path(path).write_bytes(data)

    def file_size(self, path: str) -> int | None:
        return Path(path).stat().st_size if Path(path).is_file() else None

    def file_url(self, path: str) -> str:
        return self.share_bytes(self.read_file(path), "application/pdf")

    def reveal_file(self, path: str) -> None:
        self.opened.append(f"reveal:{path}")

    def open_folder(self, path: str) -> None:
        self.opened.append(path)

    def open_url(self, url: str) -> None:
        self.opened.append(f"url:{url}")

    def show(self) -> None:
        pass

    def quit(self) -> None:
        self.events.append(("quit", None))

    def apply_theme(self, dark: bool) -> None:
        self.events.append(("theme", dark))

    def share_bytes(self, data: bytes, content_type: str) -> str:
        return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"

    def upload_url(self) -> str:
        url = f"subida-{len(self.uploads)}"
        self.uploads[url] = None
        return url

    def uploaded(self, url: str) -> bytes | None:
        return self.uploads.pop(url, None)

    def run_engine(self, task: str, data: bytes, args: dict) -> bytes:
        return run_engine(task, data, args)

    def engine_done(self, task_id: int, error: str | None) -> None:
        self.events.append(("engine_done", (task_id, error)))

    def emit(self, event: str, payload: object = None) -> None:
        self.events.append((event, payload))
        if event == "document:open":
            self.opened.append(payload["path"])


def _make_pdf(path: Path, pages: int, password: str | None = None) -> Path:
    data = pdf_bytes([[(72, 72, f"{path.stem} {i + 1}")] for i in range(pages)])
    path.write_bytes(encrypted(data, password) if password else data)
    return path


@pytest.fixture(autouse=True)
def isolated_recent_files(tmp_path, monkeypatch):
    """Los recientes van a un archivo temporal, nunca al del usuario."""
    from pdf_core import recent_files

    monkeypatch.setattr(recent_files, "_STORE", tmp_path / "recent.json")


def _merge_service(host: FakeHost) -> MergeService:
    return MergeService(host, DocumentService(host))


# ── RPC ──────────────────────────────────────────────────────────────────────
class _Service:
    @exposed
    def ok(self, x: int) -> int:
        return x * 2

    @exposed
    def fails(self) -> None:
        raise UserError("mensaje para el usuario", "custom")

    @exposed
    def crashes(self) -> None:
        raise RuntimeError("boom")

    def hidden(self) -> str:
        return "no expuesto"


def test_rpc_dispatch_only_exposes_marked_methods():
    reg = Registry()
    reg.register("svc", _Service())
    assert reg.methods() == ["svc.crashes", "svc.fails", "svc.ok"]
    assert reg.dispatch("svc.ok", [21]) == {"ok": True, "value": 42}
    assert reg.dispatch("svc.hidden")["error"]["code"] == "unknown_method"
    assert reg.dispatch("svc.fails")["error"] == {"code": "custom", "message": "mensaje para el usuario"}
    assert reg.dispatch("svc.crashes")["error"]["code"] == "internal"


def test_registry_exposes_app_and_merge(tmp_path):
    reg, services = build_registry(FakeHost(), Settings(tmp_path / "s.json"))
    assert {"app.settings", "app.set_theme", "merge.state", "merge.merge"} <= set(reg.methods())
    assert reg.dispatch("app.set_theme", [True])["ok"]
    assert reg.dispatch("app.settings")["value"] == {"dark_theme": True}
    assert json.loads((tmp_path / "s.json").read_text())["dark_theme"] is True
    for s in services.values():
        getattr(s, "close", lambda: None)()


# ── Servicio Combinar ────────────────────────────────────────────────────────
@pytest.fixture
def two_pdfs(tmp_path):
    return _make_pdf(tmp_path / "b.pdf", 3), _make_pdf(tmp_path / "a.pdf", 2)


def test_merge_selection_reorder_and_merge(tmp_path, two_pdfs):
    out = tmp_path / "out.pdf"
    host = FakeHost(picks=[str(p) for p in two_pdfs], save_to=str(out))
    svc = _merge_service(host)
    try:
        res = svc.pick_files()
        assert res["locked"] == [] and res["errors"] == []
        state = res["state"]
        assert [e["name"] for e in state["entries"]] == ["b.pdf", "a.pdf"]
        assert len(state["preview"]) == 5
        assert state["output"].endswith(".pdf")

        # Volver a cargar el mismo archivo no lo duplica.
        assert len(svc.add_paths([str(two_pdfs[0])])["state"]["entries"]) == 2

        b, a = (e["id"] for e in state["entries"])
        state = svc.set_range(b, "1, 3")
        assert state["entries"][0]["range"] == "1, 3"
        state = svc.sort_by_name()
        assert [e["name"] for e in state["entries"]] == ["a.pdf", "b.pdf"]
        state = svc.rotate(a, 90)
        assert state["entries"][0]["rotation"] == 90

        keys = [tuple(k) for k in state["preview"]]
        assert keys == [(a, 0), (a, 1), (b, 0), (b, 2)]
        interleaved = [[b, 2], [a, 0], [b, 0], [a, 1]]
        assert svc.reorder(interleaved)["preview"] == interleaved
        with pytest.raises(UserError):
            svc.reorder([[a, 0]])  # no coincide con las páginas de la vista previa

        thumbs = svc.thumbnails(a, [0, 1, 99])
        assert set(thumbs) == {"0", "1"} and thumbs["0"].startswith("data:image/png;base64,")

        svc.choose_output()
        result = svc.merge({"bookmarks": True, "duplex": False})
        assert result["count"] == 4 and result["path"] == str(out)
        assert host.events[-1] == ("merge:progress", {"done": 4, "total": 4})
        with Document.open(out) as doc:
            assert [page.text().strip() for page in doc] == ["b 3", "a 1", "b 1", "a 2"]
            assert doc[1].rotation == 90
            assert doc.toc() == [(1, "b", 0), (1, "a", 1), (1, "b", 2), (1, "a", 3)]  # uno por archivo
        svc.open_result()
        assert host.opened == [str(out)]
    finally:
        svc.close()


def test_merge_password_flow(tmp_path):
    locked = _make_pdf(tmp_path / "secreto.pdf", 1, password="clave")
    svc = _merge_service(FakeHost())
    try:
        res = svc.add_paths([str(locked)])
        assert res["locked"] == [str(locked.resolve())] and res["state"]["entries"] == []
        with pytest.raises(UserError, match="Contraseña incorrecta"):
            svc.unlock(res["locked"][0], "mal")
        state = svc.unlock(res["locked"][0], "clave")
        assert [e["name"] for e in state["entries"]] == ["secreto.pdf"]
    finally:
        svc.close()


def test_merge_without_pages_is_a_user_error(tmp_path, two_pdfs):
    svc = _merge_service(FakeHost(save_to=str(tmp_path / "x.pdf")))
    try:
        state = svc.add_paths([str(two_pdfs[0])])["state"]
        svc.select_all(state["entries"][0]["id"], False)
        with pytest.raises(UserError, match="No hay páginas"):
            svc.merge()
        assert svc.state()["busy"] is False
    finally:
        svc.close()


# ── Documentos, recientes y visor ────────────────────────────────────────────
def test_documents_open_asks_the_frontend_and_manages_recent_files(tmp_path, two_pdfs):
    host = FakeHost(picks=[str(p) for p in two_pdfs])
    docs = DocumentService(host)
    assert docs.open_dialog() == [str(p) for p in two_pdfs]
    docs.open(str(two_pdfs[0]), "clave")
    assert host.events[-1] == ("document:open", {"path": str(two_pdfs[0]), "password": "clave"})
    assert host.opened == [str(two_pdfs[0]), str(two_pdfs[1]), str(two_pdfs[0])]
    with pytest.raises(UserError):
        docs.open(str(tmp_path / "no_existe.pdf"))

    # Los recientes los añade el visor al abrir el documento con éxito.
    viewer = ViewerService(host)
    try:
        for p in two_pdfs:
            viewer.open(str(p))
    finally:
        viewer.close()
    assert ("recent:changed", None) in host.events
    assert [f["name"] for f in docs.recent()] == ["a.pdf", "b.pdf"]  # el último abierto, primero
    assert [f["name"] for f in docs.remove_recent(str(two_pdfs[1].resolve()))] == ["b.pdf"]
    assert docs.clear_recent() == []


def test_viewer_open_and_close(tmp_path):
    pdf = tmp_path / "doc.pdf"
    with Document.new() as doc:
        add_text(add_page(doc, 200, 300), 20, 40, "uno")
        add_page(doc, 300, 200)
        data = doc.to_bytes()
    data = run_engine("outline", data, {"items": [{"title": "Inicio", "page": 0}, {"title": "Detalle", "page": 1}]})
    pdf.write_bytes(run_engine("meta", data, {"metadata": {"title": "Prueba", "author": "Yo"}}))

    svc = ViewerService(FakeHost())
    try:
        info = svc.open(str(pdf))
        assert info["name"] == "doc.pdf" and info["pages"] == [[200, 300], [300, 200]]
        assert info["toc"] == [{"level": 1, "title": "Inicio", "page": 0}, {"level": 1, "title": "Detalle", "page": 1}]
        assert svc.open(str(pdf))["id"] == info["id"]  # ya abierto: el mismo documento

        assert svc.file_size(info["id"]) == pdf.stat().st_size  # lo demás de las propiedades, del visor

        svc.close_document(info["id"])
        with pytest.raises(UserError, match="ya no está abierto"):
            svc.document_url(info["id"])
        with pytest.raises(UserError, match="no encontrado"):
            svc.open(str(tmp_path / "falta.pdf"))
    finally:
        svc.close()


def test_viewer_password_errors_let_the_frontend_retry(tmp_path):
    locked = _make_pdf(tmp_path / "secreto.pdf", 1, password="clave")
    svc = ViewerService(FakeHost())
    try:
        with pytest.raises(UserError) as required:
            svc.open(str(locked))
        assert required.value.code == "password_required"
        with pytest.raises(UserError) as wrong:
            svc.open(str(locked), "mal")
        assert wrong.value.code == "invalid_password"
        info = svc.open(str(locked), "clave")
        assert len(info["pages"]) == 1
        viewer = FakeViewer(svc, info["id"])
        viewer.sync()
        assert _text(svc, info["id"], 0) == "secreto 1"
    finally:
        svc.close()


class FakeViewer:
    """Hace de visor (``Viewer.svelte``) en las pruebas de los servicios.

    Tiene su documento (el PDF que abre EmbedPDF con ``document_url``) y la clave de cada página;
    cambia las páginas con el motor de EmbedPDF (``tests/engine_task.mjs``); da a Python las claves
    y el texto de las páginas que le faltan (como ``document/text.ts``, en el formato de
    ``lib/pdf-engine/page-text.ts``) y le sube su copia al guardar. Las palabras del OCR las escribe
    en su documento con el motor (:meth:`write_ocr`, como ``canvas.writeOcrText``) cuando la prueba
    se lo pide; lo que sale de él va sin ellas (lo quita el motor: ``tests/test_pdf.py``).
    """

    def __init__(self, svc: ViewerService, doc_id: int) -> None:
        served = svc.document_url(doc_id)
        self.svc, self.doc_id = svc, doc_id
        self.password = served["password"]
        self.data = base64.b64decode(served["url"].split(",", 1)[1])
        self.keys: list[str] = list(served["keys"])
        self.with_ocr = False  # su documento tiene texto del OCR

    def sync(self, pages: list[int] | None = None) -> dict:
        """Python recibe las páginas y el texto de ``pages`` (sin ellas, de todas) que le falta."""
        result = self.svc.set_pages(self.doc_id, self.keys)
        wanted = [i for i in result["missing"] if pages is None or i in pages]
        if wanted:
            meta, data = self._texts(wanted)
            self.svc.add_texts(self.doc_id, _put(self.svc, data), meta)
        return result

    def _texts(self, indices: list[int]) -> tuple[list[dict], bytes]:
        """El texto de esas páginas como lo da el motor, con las palabras del OCR que tengan. Sin texto
        del OCR en el documento lo lee Python, que da lo mismo y más rápido
        (``test_engine_gives_python_the_same_page_text_without_the_ocr``)."""
        if self.with_ocr:
            out = json.loads(run_engine("texts", self.data, {"indices": indices, "password": self.password}))
            return out["pages"], base64.b64decode(out["data"])
        with Document.open(self.data, self.password) as doc:
            return pack_page_texts([(i, doc[i].page_text()) for i in indices])

    def write_ocr(self, index: int, words: list, replace: bool = True) -> None:
        """Escribe en su documento las palabras de un OCR como texto invisible (``canvas.writeOcrText``)."""
        items = [{"index": index, "words": [list(w) for w in words], "replace": replace}]
        self.data = run_engine("ocr-write", self.data, {"pages": items, "password": self.password})
        self.with_ocr = True

    def recognized(self, index: int, words: list[tuple]) -> None:
        """Lo que queda tras el OCR de la página ``index``: Python guarda sus palabras (servicio
        ``ocr``) y el visor las escribe en su documento."""
        with self.svc.document(self.doc_id) as entry:
            self.svc.set_ocr_words(entry, self.keys[index], words)
        self.write_ocr(index, words)

    def reshape(self, ops: list[list], uids: list[int]) -> dict:
        """Cambia las páginas (``ops``, como en ``engine_task.mjs``); ``uids``: el id de cada página
        que queda (los da el visor). Devuelve lo que dice Python al recibirlas."""
        self.data = run_engine("pages", self.data, {"ops": ops, "password": self.password})
        revisions = {key.split(":")[0]: key.split(":")[2] for key in self.keys}
        with Document.open(self.data, self.password) as doc:
            self.keys = [f"{uid}:{page.rotation}:{revisions.get(str(uid), 0)}" for uid, page in zip(uids, doc, strict=True)]
        return self.sync()

    def annotate(self, edit) -> dict:
        """Cambia con ``edit(documento)`` las anotaciones de su documento y se lo dice a Python."""
        with Document.open(self.data, self.password) as doc:
            edit(doc)
            self.data = doc.to_bytes()
        return self.svc.annotations_changed(self.doc_id)

    def save(self, method: str = "save") -> dict | None:
        """Guarda (``save`` o ``save_as``): sube su copia del documento con la clave de cada página."""
        return getattr(self.svc, method)(self.doc_id, _put(self.svc, self.data), self.keys)

    def redact(self, service: RedactService, marks: list[tuple[int, list[float]]], color: str = "#000000") -> dict:
        """Aplica marcas de censura (página, rectángulo sin girar) como ``redact/apply.ts``: el motor en
        su documento y después ``redact.apply``. Devuelve lo que responde Python."""
        indices = sorted({page for page, _rect in marks})
        items = [{"page": page, "rect": rect, "color": color} for page, rect in marks]
        marked = run_engine("mark", self.data, {"marks": items, "password": self.password})
        self.data = run_engine("redact", marked, {"password": self.password})
        before = list(self.keys)
        for i in indices:
            uid, rotation, revision = self.keys[i].split(":")
            self.keys[i] = f"{uid}:{rotation}:{int(revision) + 1}"
        pages = [{"before": before[i], "after": self.keys[i]} for i in indices]
        return service.apply(self.doc_id, pages)

    def document(self) -> Document:
        return Document.open(self.data, self.password)


def test_viewer_takes_the_pages_from_the_viewer(tmp_path):
    pdf = _make_pdf(tmp_path / "ops.pdf", 3)
    svc = ViewerService(FakeHost())
    try:
        info = svc.open(str(pdf))
        doc_id = info["id"]
        assert info["modified"] is False and info["keys"] == ["1:0:0", "2:0:0", "3:0:0"]
        viewer = FakeViewer(svc, doc_id)
        ops = [["rotate", [0], 1], ["blank", 1, 595, 842], ["duplicate", 2, 3], ["move", 4, 0], ["remove", 2]]
        # [3, 1↻, 2, 2'], con los id que da el visor (4 era la blanca, ya borrada; 5 es la copia).
        result = viewer.reshape(ops, [3, 1, 2, 5])
        assert viewer.keys == ["3:0:0", "1:90:0", "2:0:0", "5:0:0"]
        assert result["modified"] and result["missing"] == [0, 1, 2, 3] and svc.unsaved_documents() == ["ops.pdf"]
        assert viewer.sync()["missing"] == []  # el texto de cada versión de una página llega una vez

        saved = viewer.save()
        assert saved["modified"] is False and saved["annotated"] is False and svc.unsaved_documents() == []
        assert page_texts(pdf) == ["ops 3", "ops 1", "ops 2", "ops 2"]
        assert _text(svc, doc_id, 0) == "ops 3"
        # Python no tiene el documento: lo que vuelve a abrir el visor es el archivo guardado.
        assert svc.document_url(doc_id)["keys"] == viewer.keys
        with pytest.raises(UserError, match="no son válidas"):
            svc.set_pages(doc_id, ["3:0"])
    finally:
        svc.close()


def test_viewer_keeps_ocr_words_while_their_page_moves_or_turns(tmp_path):
    pdf = _make_pdf(tmp_path / "ocr.pdf", 2)
    svc = ViewerService(FakeHost())
    try:
        doc_id = svc.open(str(pdf))["id"]
        viewer = FakeViewer(svc, doc_id)
        viewer.sync()
        viewer.recognized(0, [(100, 300, 220, 320, "reconocido")])
        # El visor la lleva al final y la gira: sus palabras van con ella, donde se ven ahora.
        viewer.reshape([["move", 0, 1], ["rotate", [1], 1]], [2, 1])
        assert "reconocido" in _text(svc, doc_id, 1)
        with svc.document(doc_id) as entry:
            ((*box, word, turn),) = entry.ocr["1:90:0"]
        assert word == "reconocido" and turn == 90
        assert box == pytest.approx([842 - 320, 100, 842 - 300, 220], abs=0.05)
        # Se deshace el giro en el visor: la página vuelve con su clave y con sus palabras.
        viewer.reshape([["rotate", [1], -1]], [2, 1])
        assert "reconocido" in _text(svc, doc_id, 1)
    finally:
        svc.close()


def test_a_copied_page_keeps_its_ocr_words_for_the_ai_and_export(tmp_path):
    """La copia de una página (otra clave) lleva el texto del OCR en el visor: Python lo recibe con
    su texto, y así lo ven el asistente IA y exportar texto."""
    pdf = _blank_pdf(tmp_path / "escaneo.pdf", 2)
    host = FakeHost(save_to=str(tmp_path / "texto.txt"))
    svc = ViewerService(host)
    try:
        doc_id = svc.open(str(pdf))["id"]
        viewer = FakeViewer(svc, doc_id)
        viewer.sync()
        viewer.recognized(0, [(100, 300, 220, 320, "reconocido")])
        assert viewer.reshape([["duplicate", 0, 1]], [1, 3, 2])["missing"] == [1]
        assert "reconocido" in _text(svc, doc_id, 1)
        svc.export_text(doc_id)
        assert (tmp_path / "texto.txt").read_text(encoding="utf-8").count("reconocido") == 2
        # Lo que reconoce Python de una página sustituye a lo que tenía.
        viewer.recognized(1, [(100, 300, 220, 320, "nuevo")])
        assert "nuevo" in _text(svc, doc_id, 1) and "reconocido" not in _text(svc, doc_id, 1)
        # Las guarda con su clave: si el visor vuelve a abrir el archivo guardado, las escribe.
        viewer.save()
        assert [page["index"] for page in svc.document_url(doc_id)["ocr"]] == [0, 1]
    finally:
        svc.close()


class WindowFilesHost(FakeHost):
    """Los archivos los tiene la ventana, no el disco (como en el navegador)."""

    def __init__(self, files: dict[str, bytes], **kw) -> None:
        super().__init__(**kw)
        self.files = files

    def read_file(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_file(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def file_size(self, path: str) -> int | None:
        return len(self.files[path]) if path in self.files else None


def test_viewer_only_touches_its_files_through_the_host(tmp_path):
    path = str(tmp_path / "ventana" / "doc.pdf")  # no existe en disco
    copy = str(tmp_path / "ventana" / "copia.pdf")
    data = pdf_bytes([[(72, 72, "uno")], [(72, 72, "dos")]])
    host = WindowFilesHost({path: data}, save_to=copy)
    svc = ViewerService(host)
    try:
        doc_id = svc.open(path)["id"]
        viewer = FakeViewer(svc, doc_id)
        assert viewer.data == data and svc.file_size(doc_id) == len(data)
        viewer.reshape([["remove", 0]], [2])
        viewer.save()
        viewer.save("save_as")
        assert page_texts(host.files[path]) == page_texts(host.files[copy]) == ["dos"]
        assert not (tmp_path / "ventana").exists()
        with pytest.raises(UserError) as ex:
            svc.open(str(tmp_path / "ventana" / "otro.pdf"))
        assert ex.value.code == "not_found"
    finally:
        svc.close()


def test_viewer_save_as_moves_the_tab_to_the_new_file(tmp_path):
    pdf = _make_pdf(tmp_path / "original.pdf", 2)
    copy = tmp_path / "copia"  # sin extensión: se añade .pdf
    host = FakeHost(save_to=str(copy))
    svc = ViewerService(host)
    try:
        doc_id = svc.open(str(pdf))["id"]
        viewer = FakeViewer(svc, doc_id)
        viewer.reshape([["remove", 0]], [2])
        info = viewer.save("save_as")
        assert info["path"] == str(tmp_path / "copia.pdf") and info["name"] == "copia.pdf"
        assert not info["modified"] and host.saved_suggestions == [str(pdf)]
        assert page_texts(tmp_path / "copia.pdf") == ["original 2"]
        assert page_texts(pdf) == ["original 1", "original 2"]  # el original no cambia
        reopened = svc.open(str(tmp_path / "copia.pdf"))
        assert reopened["id"] == doc_id and reopened["keys"] == ["2:0:0"] and len(reopened["pages"]) == 1

        host.save_to = None
        assert viewer.save("save_as") is None  # cancelado
    finally:
        svc.close()


def test_viewer_save_writes_the_viewer_copy_as_is(tmp_path):
    pdf = _make_pdf(tmp_path / "tal_cual.pdf", 2)
    svc = ViewerService(FakeHost())
    try:
        doc_id = svc.open(str(pdf))["id"]
        viewer = FakeViewer(svc, doc_id)
        viewer.reshape([["move", 1, 0]], [2, 1])
        assert not viewer.save()["modified"]
        assert pdf.read_bytes() == viewer.data  # sin volver a generarla en Python

        with pytest.raises(UserError) as error:
            svc.save(doc_id, _put(svc, b"esto no es un PDF"), viewer.keys)
        assert error.value.code == "sync_failed" and pdf.read_bytes() == viewer.data  # no se escribe
        with pytest.raises(UserError) as error:
            svc.save(doc_id, _put(svc, viewer.data), viewer.keys[:1])  # una clave por página
        assert error.value.code == "sync_failed"
        with pytest.raises(UserError) as error:
            svc.save(doc_id, svc.upload_url(), viewer.keys)  # no llegó nada
        assert error.value.code == "upload_missing"
    finally:
        svc.close()


def test_viewer_save_keeps_the_password(tmp_path):
    locked = _make_pdf(tmp_path / "secreto.pdf", 2, password="clave")
    svc = ViewerService(FakeHost())
    try:
        doc_id = svc.open(str(locked), "clave")["id"]
        viewer = FakeViewer(svc, doc_id)
        assert viewer.password == "clave"
        viewer.reshape([["rotate", [1], 1]], [1, 2])
        viewer.save()
    finally:
        svc.close()
    with pytest.raises(PasswordError):
        Document.open(locked)
    with Document.open(locked, "clave") as doc:
        assert doc.encrypted and doc[1].rotation == 90 and doc[0].text().strip() == "secreto 1"


def test_viewer_save_respects_the_pdf_permissions(tmp_path):
    pdf = tmp_path / "solo_lectura.pdf"
    pdf.write_bytes(encrypted(pdf_bytes([[(72, 72, "fijo")]]), "", owner="dueño", permissions=0))
    svc = ViewerService(FakeHost())
    try:
        doc_id = svc.open(str(pdf))["id"]
        with pytest.raises(UserError) as error:
            FakeViewer(svc, doc_id).save()
        assert error.value.code == "save_not_allowed"
    finally:
        svc.close()


def test_viewer_exports_page_text_and_images(tmp_path):
    pdf = tmp_path / "fuente.pdf"
    with Document.new() as doc:
        page = add_page(doc)
        add_text(page, 72, 72, "hola")
        add_image(page, Rect(100, 100, 140, 140), np.full((4, 4, 3), 90, np.uint8))
        add_text(add_page(doc), 72, 72, "adiós")
        doc.save(pdf)
    out = tmp_path / "salida"
    out.mkdir()
    host = FakeHost(save_to=str(tmp_path / "pagina.pdf"), folder=str(out))
    svc = ViewerService(host)
    try:
        doc_id = svc.open(str(pdf))["id"]
        viewer = FakeViewer(svc, doc_id)
        page = run_engine("extract", viewer.data, {"indices": [1], "withoutText": []})  # la saca el visor
        assert svc.extract_page(doc_id, 1, _put(svc, page)) == str(tmp_path / "pagina.pdf")
        assert host.saved_suggestions[-1] == str(tmp_path / "fuente_pagina_2.pdf")
        assert page_texts(tmp_path / "pagina.pdf") == ["adiós"]

        host.save_to = str(tmp_path / "texto.txt")
        with pytest.raises(UserError) as error:
            svc.export_text(doc_id)  # sin el texto de las páginas
        assert error.value.code == "text_missing"
        viewer.sync()
        svc.export_text(doc_id)
        assert host.saved_suggestions[-1] == str(tmp_path / "fuente_texto.txt")
        text = (tmp_path / "texto.txt").read_text(encoding="utf-8")
        assert "=== PÁGINA 1 ===\nhola" in text and "=== PÁGINA 2 ===\nadiós" in text

        assert svc.export_images(doc_id, _put(svc, viewer.data)) == {"folder": str(out), "count": 1}
        assert [p.name for p in out.iterdir()] == ["fuente_p1_img1.png"]
    finally:
        svc.close()


def test_viewer_rejects_page_texts_that_do_not_fit(tmp_path):
    pdf = _make_pdf(tmp_path / "texto.pdf", 1)
    svc = ViewerService(FakeHost())
    try:
        doc_id = svc.open(str(pdf))["id"]
        svc.set_pages(doc_id, ["1:0:0"])
        with pytest.raises(UserError) as error:
            svc.add_texts(doc_id, _put(svc, b"corto"), [{"index": 0, "geometry": [1, 1, 0, 1, 0], "count": 2}])
        assert error.value.code == "bad_texts"
        meta, data = pack_page_texts([])
        with pytest.raises(UserError, match="fuera de rango"):
            svc.add_texts(doc_id, _put(svc, data), [{"index": 3, "geometry": [1, 1, 0, 1, 0], "count": 0}])
    finally:
        svc.close()


def _lines_pdf(path: Path, pages: list[list[str]]) -> Path:
    path.write_bytes(pdf_bytes([[(72, 72 + 20 * i, line) for i, line in enumerate(lines)] for lines in pages]))
    return path


def test_viewer_text_layer_follows_reading_order(tmp_path):
    pdf = _lines_pdf(tmp_path / "texto.pdf", [["Hola mundo", "segunda linea"]])
    svc = ViewerService(FakeHost())
    try:
        info = svc.open(str(pdf))
        viewer = FakeViewer(svc, info["id"])
        viewer.sync()
        assert _text(svc, info["id"], 0) == "Hola mundo\nsegunda linea"
        viewer.reshape([["rotate", [0], 1]], [1])
        # Girada se lee igual; los rectángulos ya están en la página girada (apaisada).
        assert _text(svc, info["id"], 0).startswith("Hola mundo")
        with svc.document(info["id"]) as entry:
            assert max(r.x0 for r in svc.text_of(entry, 0).rects) > 600
    finally:
        svc.close()


def _served(svc: ViewerService, doc_id: int) -> Document:
    """El documento como lo abre EmbedPDF (``document_url``)."""
    served = svc.document_url(doc_id)
    return Document.open(base64.b64decode(served["url"].split(",", 1)[1]), served["password"])


def _put(svc: ViewerService, data: bytes) -> str:
    """Hace de visor: sube ``data``; devuelve la URL que se pasa al servicio."""
    url = svc.upload_url()
    svc._host.uploads[url] = data
    return url


def test_viewer_annotations_go_to_the_file_with_the_viewer_copy(tmp_path):
    pdf = tmp_path / "notas.pdf"
    with Document.new() as doc:
        for i in range(2):
            add_text(add_page(doc), 72, 72, f"Pagina {i + 1}")
        add_annot(doc[0], "Link", Rect(70, 60, 200, 80))
        add_annot(doc[1], "Square", Rect(100, 100, 200, 160))
        doc.save(pdf)
    svc = ViewerService(FakeHost())
    try:
        info = svc.open(str(pdf))
        doc_id = info["id"]
        assert "annotations" not in info and not info["modified"]
        with _served(svc, doc_id) as copy:  # EmbedPDF recibe las anotaciones: las edita él
            assert [annots(page) for page in copy] == [["Link"], ["Square"]]

        viewer = FakeViewer(svc, doc_id)
        viewer.sync()
        with svc.document(doc_id) as entry:  # OCR en la página 2: no va al archivo
            svc.set_ocr_words(entry, viewer.keys[1], [(300, 300, 360, 320, "reconocido")])

        def edit(copy):
            add_annot(copy[0], "Highlight", Rect(70, 60, 140, 80))
            delete_annots(copy[1])
            add_annot(copy[1], "Text", Rect(300, 300, 320, 320), "nota")

        assert viewer.annotate(edit) == {"modified": True}
        assert svc.unsaved_documents() == ["notas.pdf"]
        assert not viewer.save()["modified"] and svc.unsaved_documents() == []
        with Document.open(pdf) as doc:
            assert [annots(page) for page in doc] == [["Link", "Highlight"], ["Text"]]
            assert doc[1].text().strip() == "Pagina 2"  # sin el texto de OCR

        # Al mover páginas en el visor, el OCR sigue a su página.
        viewer.reshape([["move", 1, 0]], [2, 1])
        assert "reconocido" in _text(svc, doc_id, 0)
    finally:
        svc.close()


def test_legends_menu_and_store(tmp_path, monkeypatch):
    from app.backend.services.legends import LegendsService
    from pdf_core import legends

    monkeypatch.setattr(legends, "_LEGENDS_FILE", tmp_path / "leyendas.json")
    monkeypatch.setattr(legends, "_singleton", None)
    svc = LegendsService()
    menu = svc.menu()
    assert menu["stamps"][0] == {"text": "CONFIDENCIAL", "color": "#D32F2F"} and menu["favorites"] == []

    (legend,) = svc.create("  PAGADO ", "#1565c0", 20)
    assert legend["text"] == "PAGADO" and legend["color"] == "#1565C0" and legend["font_size"] == 20
    svc.used(legend["id"])
    assert [x["name"] for x in svc.menu()["favorites"]] == ["PAGADO"]
    assert '"PAGADO"' in (tmp_path / "leyendas.json").read_text(encoding="utf-8")
    with pytest.raises(UserError, match="texto"):
        svc.create("  ", "#000000")
    with pytest.raises(UserError, match="Color"):
        svc.create("X", "rojo")
    assert svc.delete(legend["id"]) == []


def test_stamps_library_store():
    from app.backend.services import stamps
    from app.backend.services.stamps import StampsService

    svc = StampsService()
    assert svc.library() is None
    pdf = base64.b64encode(pdf_bytes([[]], size=(120, 40))).decode("ascii")
    entries = [{"id": "a1", "pageIndex": 0, "name": 36, "subject": "Mi sello"}]
    svc.save_library(pdf, entries)
    assert svc.library() == {"pdf": pdf, "stamps": entries}
    assert not list(stamps.STORE.glob("*.tmp"))  # se escribe en un temporal y se renombra
    with pytest.raises(UserError, match="no es válida"):
        svc.save_library(base64.b64encode(b"no es un pdf").decode("ascii"), entries)
    with pytest.raises(UserError, match="no es válida"):
        svc.save_library("%%%", entries)
    assert svc.library() == {"pdf": pdf, "stamps": entries}  # lo guardado sigue intacto
    svc.save_library(None, [])
    assert svc.library() is None and not (stamps.STORE / "custom.pdf").exists()


def test_stamps_signatures_store():
    from app.backend.services import stamps
    from app.backend.services.stamps import StampsService

    svc = StampsService()
    assert svc.signatures() == []
    entry = {"id": "s1", "createdAt": 1, "signature": {"creationType": "type", "previewDataUrl": "data:,", "imageData": "AA=="}}
    svc.save_signatures([entry])
    assert svc.signatures() == [entry]
    (stamps.STORE / "signatures.json").write_text("{roto", encoding="utf-8")
    assert svc.signatures() == []  # un archivo dañado no rompe el visor
    svc.save_signatures([])
    assert not (stamps.STORE / "signatures.json").exists()


def test_app_quit_closes_without_asking(tmp_path):
    host = FakeHost()
    AppService(host, Settings(tmp_path / "s.json")).quit()
    assert ("quit", None) in host.events


# ── Imprimir (visor) ─────────────────────────────────────────────────────────
def test_select_pages_for_print_and_batches():
    from pdf_core.page_ranges import select_pages

    assert select_pages(5, "all") == [0, 1, 2, 3, 4]
    assert select_pages(5, "current", current=3) == [3]
    assert select_pages(5, "custom", "5, 2-3, 9") == [1, 2, 4]
    assert select_pages(5, "odd") == [0, 2, 4] and select_pages(5, "even") == [1, 3]
    assert select_pages(5, "all", subset="even", reverse=True) == [3, 1]  # páginas 4 y 2
    assert select_pages(5, "custom", "2-5", subset="odd") == [2, 4]
    with pytest.raises(ValueError):
        select_pages(5, "algunas")


# ── Servicio OCR (visor) ─────────────────────────────────────────────────────
class ScriptedOCR:
    """El ``OCRProcessor`` real salvo los modelos: reconoce siempre ``words``.

    ``words``: [(x0, y0, x1, y1, texto)] en fracciones de la imagen que recibe el
    modelo, así se prueban la rasterización y el paso de píxeles a puntos.
    """

    def __new__(cls, words, angle=0):
        from pdf_core.ocr import OCRProcessor

        class _Scripted(OCRProcessor):
            def _run_predictor(self, img):
                h, w = img.shape[:2]
                return [(Rect(x0 * w, y0 * h, x1 * w, y1 * h), t, 0.9) for x0, y0, x1, y1, t in self.words], 0.01

            def classify_orientation(self, img):
                return self.angle, 1.0

        processor = _Scripted(".")
        processor.words, processor.angle = words, angle
        return processor


def _text(svc: ViewerService, doc_id: int, index: int) -> str:
    """Texto de la página en orden de lectura (nativo y de OCR), como lo leen la IA y la exportación."""
    with svc.document(doc_id) as entry:
        return svc.text_of(entry, index).text


def _served_text(svc: ViewerService, doc_id: int) -> list[str]:
    """Texto de cada página del documento como lo tiene EmbedPDF al abrirlo (el que selecciona y
    busca): el de ``document_url`` con las palabras del OCR que escribe en él el visor (canvas.ts)."""
    served = svc.document_url(doc_id)
    data = base64.b64decode(served["url"].split(",", 1)[1])
    if served["ocr"]:
        pages = [{**page, "replace": False} for page in served["ocr"]]
        data = run_engine("ocr-write", data, {"pages": pages, "password": served["password"]})
    with Document.open(data, served["password"]) as doc:
        return [page.text() for page in doc]


def _region(viewer: FakeViewer, index: int, rect: list[float] | None = None, scale: float = 1.0) -> tuple[str, dict]:
    """Hace de visor (ocr/recognize.ts): dibuja ``rect`` de la página (sin él, la página entera) y
    lo sube; devuelve la URL y la región que se pasa al servicio ``ocr``."""
    with viewer.document() as doc:
        page = doc[index]
        rect = rect or [0, 0, page.rect.width, page.rect.height]
        image = page.render(scale, clip=rect)
    height, width = image.shape[:2]
    return _put(viewer.svc, image.tobytes()), {"rect": rect, "scale": scale, "width": width, "height": height}


def _ocr_page(ocr: OcrService, viewer: FakeViewer, index: int) -> dict:
    """«Procesar Página Actual» (ocr/recognize.ts): el visor escribe en su documento lo que devuelve."""
    viewer.sync([index])
    url, region = _region(viewer, index)
    result = ocr.page(viewer.doc_id, index, url, [region], {"lines": 0, "images": False})
    viewer.write_ocr(index, result["words"])
    return result


def _ocr_area(ocr: OcrService, viewer: FakeViewer, index: int, rect: list[float]) -> dict:
    """El OCR de un recorte: sus palabras se suman a las de la página, también en el visor."""
    viewer.sync([index])
    url, region = _region(viewer, index, rect, scale=2)
    result = ocr.area(viewer.doc_id, index, url, region)
    viewer.write_ocr(index, result["words"], replace=False)
    return result


def _blank_pdf(path: Path, pages: int, native: dict[int, str] | None = None) -> Path:
    path.write_bytes(pdf_bytes([[(72, 72, native[i])] if native and i in native else [] for i in range(pages)], size=(600, 800)))
    return path


def test_ocr_words_join_the_text_layer_search_and_export(tmp_path):
    pdf = _blank_pdf(tmp_path / "escaneo.pdf", 2)
    host = FakeHost(save_to=str(tmp_path / "texto.txt"))
    svc = ViewerService(host)
    # Palabras seguidas en una línea (a 0.07 de ancho de página = 42 pt entre centros).
    words = [(0.1 + 0.07 * i, 0.1, 0.16 + 0.07 * i, 0.13, w) for i, w in enumerate(["Hola", "mundo", "desde", "OCR"])]
    ocr = OcrService(host, svc, ScriptedOCR(words))
    try:
        doc_id = svc.open(str(pdf))["id"]
        viewer = FakeViewer(svc, doc_id)
        viewer.sync([0])
        before = ocr.page_text(doc_id, 0, images=True)
        assert before == {"page": 0, "text": "", "segments": 0, "boxes": [], "kind": "Escaneado", "ocr": False}

        result = _ocr_page(ocr, viewer, 0)
        assert result["text"] == "Hola mundo desde OCR" and result["mode"] == "OCR" and result["kind"] == "Escaneado"
        assert result["boxes"][:2] == [[60, 80, 96, 104], [102, 80, 138, 104]]  # de píxeles a puntos
        assert [w[4] for w in result["words"]] == ["Hola", "mundo", "desde", "OCR"]  # las escribe el visor
        assert ocr.page_text(doc_id, 0)["ocr"] and ocr.page_text(doc_id, 0)["text"] == "Hola mundo desde OCR"

        assert "Hola mundo desde OCR" in _text(svc, doc_id, 0)
        assert "mundo" in _served_text(svc, doc_id)[0]  # al volver a abrirlo, EmbedPDF lo selecciona y lo busca
        viewer.sync()
        svc.export_text(doc_id)
        assert "=== PÁGINA 1 ===\nHola mundo desde OCR" in (tmp_path / "texto.txt").read_text(encoding="utf-8")

        # Un recorte suma sus palabras a las de la página.
        ocr.processor.words = [(0, 0, 1, 1, "recorte")]
        area = _ocr_area(ocr, viewer, 1, [100, 100, 200, 150])
        assert area["text"] == "recorte" and area["boxes"] == [[100, 100, 200, 150]]
        assert [list(w) for w in area["words"]] == [[100, 100, 200, 150, "recorte"]]  # solo las nuevas
        assert len(_ocr_area(ocr, viewer, 1, [300, 300, 400, 350])["boxes"]) == 2

        # Al girar la página en el visor, sus palabras van con ella (el visor se las da a Python).
        viewer.reshape([["rotate", [0], 1]], [1, 2])
        assert ocr.page_text(doc_id, 0)["ocr"] and ocr.page_text(doc_id, 0)["text"] == "Hola mundo desde OCR"

        assert ocr.save_text(doc_id, "texto reconocido") == str(tmp_path / "texto.txt")
        assert host.saved_suggestions[-1] == str(tmp_path / "escaneo_ocr.txt")
        assert (tmp_path / "texto.txt").read_text(encoding="utf-8") == "texto reconocido"
        url, region = _region(viewer, 0)
        with pytest.raises(UserError, match="fuera de rango"):
            ocr.page(doc_id, 5, url, [region], {})
        url, region = _region(viewer, 0)
        with pytest.raises(UserError) as error:  # faltan píxeles
            ocr.page(doc_id, 0, url, [{**region, "height": region["height"] + 1}], {})
        assert error.value.code == "bad_images"
    finally:
        ocr.close()
        svc.close()


def test_ocr_batch_pages_and_orientation(tmp_path):
    pdf = _blank_pdf(tmp_path / "lote.pdf", 5)
    svc = ViewerService(FakeHost())
    ocr = OcrService(FakeHost(), svc, ScriptedOCR([], angle=90))
    try:
        doc_id = svc.open(str(pdf))["id"]
        assert ocr.batch_pages(doc_id, "all", "") == [0, 1, 2, 3, 4]
        assert ocr.batch_pages(doc_id, "even", "") == [1, 3]
        assert ocr.batch_pages(doc_id, "odd", "") == [0, 2, 4]
        assert ocr.batch_pages(doc_id, "custom", "4, 2-3, 9") == [1, 2, 3]
        with pytest.raises(UserError, match="páginas válidas"):
            ocr.batch_pages(doc_id, "custom", "nada")
        with pytest.raises(UserError):
            ocr.batch_pages(doc_id, "todas", "")

        # Un escaneo, por sus imágenes (la del clasificador y la sonda): pide girar 90°. Con
        # texto, lo decide el visor por el sentido del texto (test_engine_reads_page_facts_*).
        with FakeViewer(svc, doc_id).document() as doc:
            small, probe = doc[1].render(0.8), doc[1].render(1.5)
        shapes = [{"width": i.shape[1], "height": i.shape[0]} for i in (small, probe)]
        assert ocr.orientation(_put(svc, small.tobytes() + probe.tobytes()), shapes) == {"angle": 90}  # lo gira el visor
        assert svc._info(doc_id)["modified"] is False
    finally:
        ocr.close()
        svc.close()


# ── Servicio Censura (visor) ─────────────────────────────────────────────────
@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    """Los perfiles de censura van a un archivo temporal, nunca al del usuario."""
    from pdf_core import censorship_profiles

    monkeypatch.setattr(censorship_profiles, "_PROFILES_FILE", tmp_path / "perfiles.json")
    monkeypatch.setattr(censorship_profiles, "_singleton", None)
    return tmp_path / "perfiles.json"


def _redact_pdf(path: Path) -> Path:
    with Document.new() as doc:
        page = add_page(doc, 600, 800)
        add_text(page, 72, 100, "Contrato con Juan Pérez")
        add_text(page, 72, 140, "Firmado por Juan Pérez")
        add_text(add_page(doc, 600, 800), 72, 100, "Escribir a juan@correo.com hoy")
        add_page(doc, 600, 800)  # escaneo: solo tendrá palabras de OCR
        turned = add_page(doc, 600, 800)
        add_text(turned, 72, 100, "Juan Perez en página girada")
        turned.set_rotation(90)
        doc.save(path)
    return path


def test_redact_finds_terms_patterns_and_ocr(tmp_path, isolated_profiles):
    pdf = _redact_pdf(tmp_path / "contrato.pdf")
    viewer_svc = ViewerService(FakeHost())
    svc = RedactService(viewer_svc)
    try:
        doc_id = viewer_svc.open(str(pdf))["id"]
        state = svc.state(doc_id)
        assert state == {"case_sensitive": False, "whole_word": False, "search_ocr": True, "color": "#000000", "profile": None}
        viewer = FakeViewer(viewer_svc, doc_id)
        with pytest.raises(UserError) as error:
            svc.find(doc_id, ["juan"])  # sin el texto de las páginas
        assert error.value.code == "text_missing"
        viewer.sync()

        (found,) = svc.find(doc_id, ["  juan perez ", " "])  # sin tildes ni mayúsculas; los vacíos no cuentan
        assert found["term"] == "juan perez" and found["kind"] == "texto"
        assert [m["page"] for m in found["matches"]] == [0, 0, 3]
        # En la página girada, en coordenadas de la página sin girar (600×800), como las anotaciones.
        x0, y0, x1, y1 = found["matches"][2]["rect"]
        assert x1 <= 600 and y1 <= 800 and (x1 - x0) > (y1 - y0)

        svc.set_options(doc_id, True, False, True)  # distingue mayúsculas
        assert svc.find(doc_id, ["juan perez"])[0]["matches"] == []
        svc.set_options(doc_id, False, False, True)

        email = next(p["pattern"] for p in svc.patterns() if "Correos" in p["label"])
        (found,) = svc.find(doc_id, [email])
        assert found["kind"] == "regex" and [m["page"] for m in found["matches"]] == [1]

        # Las palabras de OCR también se buscan (y se puede desactivar); en la página girada
        # vienen de la página vista y se devuelven sin girar.
        with viewer_svc.document(doc_id) as entry:
            viewer_svc.set_ocr_words(entry, viewer.keys[2], [(100, 100, 160, 120, "JUAN"), (165, 100, 230, 120, "PEREZ")])
            viewer_svc.set_ocr_words(entry, viewer.keys[3], [(500, 100, 560, 120, "Pérez")], merge=True)
        matches = svc.find(doc_id, ["pérez"])[0]["matches"]
        assert [m["page"] for m in matches] == [0, 0, 2, 3, 3]
        x0, y0, x1, y1 = matches[-1]["rect"]
        assert x1 <= 600 and y1 <= 800 and (y1 - y0) > (x1 - x0)
        svc.set_options(doc_id, False, False, False)
        assert [m["page"] for m in svc.find(doc_id, ["pérez"])[0]["matches"]] == [0, 0, 3]

        with pytest.raises(UserError, match="Color"):
            svc.set_color(doc_id, "negro")
        assert svc.set_color(doc_id, "#b71c1c")["color"] == "#B71C1C"
        with pytest.raises(UserError, match="marcas"):
            svc.apply(doc_id, [])
    finally:
        viewer_svc.close()


def test_redact_apply_removes_what_the_marks_cover_and_forces_save_as(tmp_path, isolated_profiles):
    pdf = _redact_pdf(tmp_path / "contrato.pdf")
    out = tmp_path / "copia.pdf"
    host = FakeHost(save_to=str(out))
    viewer_svc = ViewerService(host)
    svc = RedactService(viewer_svc)
    try:
        info = viewer_svc.open(str(pdf))
        doc_id = info["id"]
        viewer = FakeViewer(viewer_svc, doc_id)
        viewer.sync()
        viewer.recognized(2, [(100, 100, 160, 120, "Pérez"), (300, 300, 360, 320, "queda")])
        matches = svc.find(doc_id, ["Pérez"])[0]["matches"]  # páginas 0 y 3 (texto) y 2 (OCR); la 1 no
        assert len(matches) == 4
        state = viewer.redact(svc, [(m["page"], m["rect"]) for m in matches], color="#B21A1A")
        assert state["redacted"] and state["modified"]
        # Las páginas censuradas cambian de clave: Python pide su texto nuevo, y el visor le da las
        # palabras de OCR que quedan (la censura de su motor borró las que tapaban las marcas).
        assert viewer.sync()["missing"] == [0, 2, 3]
        with viewer_svc.document(doc_id) as entry:
            assert viewer.keys[2].endswith(":1") and [w[4] for w in entry.ocr[viewer.keys[2]]] == ["queda"]
        assert viewer_svc.set_pages(doc_id, viewer.keys)["missing"] == []
        assert not any("Pérez" in _text(viewer_svc, doc_id, i) for i in range(4))
        assert "Perez" not in _text(viewer_svc, doc_id, 3)
        assert "Juan" in _text(viewer_svc, doc_id, 0) and "queda" in _text(viewer_svc, doc_id, 2)  # lo demás sigue ahí
        with viewer.document() as doc:  # las marcas aplicadas desaparecen; el recuadro queda con su color
            assert not any(annots(page) for page in doc)
            image = doc[0].render(clip=matches[0]["rect"])
            r, g, b = image[image.shape[0] // 2, image.shape[1] // 2]
            assert r > 150 and g < 60 and b < 60

        with pytest.raises(UserError) as err:
            viewer.save()
        assert err.value.code == "redacted"
        saved = viewer.save("save_as")
        assert host.saved_suggestions[-1] == str(tmp_path / "contrato_censurado.pdf")
        assert saved["path"] == str(out) and not saved["redacted"] and not saved["modified"]
        assert "Pérez" not in page_texts(out)[0] and "Contrato con Juan" in page_texts(out)[0]
        assert "Pérez" in page_texts(pdf)[0]  # el original no se toca
        # Al volver a abrirlo, EmbedPDF tampoco lo tiene, ni en el texto del OCR.
        assert not any("Pérez" in text for text in _served_text(viewer_svc, doc_id))
    finally:
        viewer_svc.close()


def test_redact_profiles(tmp_path, isolated_profiles):
    pdf = _redact_pdf(tmp_path / "contrato.pdf")
    viewer = ViewerService(FakeHost())
    svc = RedactService(viewer)
    try:
        doc_id = viewer.open(str(pdf))["id"]
        with pytest.raises(UserError, match="al menos un término"):
            svc.save_profile(doc_id, [" "], "Vacío")
        svc.set_color(doc_id, "#0D47A1")
        with pytest.raises(UserError, match="nombre"):
            svc.save_profile(doc_id, ["Juan"])
        state = svc.save_profile(doc_id, ["Juan", "Juan"], "Clientes")
        assert state["profile"]["name"] == "Clientes"
        (profile,) = svc.profiles()
        assert profile == {"id": state["profile"]["id"], "name": "Clientes", "terms": 1}

        svc.save_profile(doc_id, ["Juan", "correo"])  # con perfil activo: actualiza
        assert svc.profiles()[0]["terms"] == 2
        assert "Clientes" in isolated_profiles.read_text(encoding="utf-8")

        svc.set_color(doc_id, "#000000")
        loaded = svc.load_profile(doc_id, profile["id"])
        assert loaded["terms"] == ["Juan", "correo"] and loaded["state"]["color"] == "#0D47A1"
        assert loaded["state"]["profile"]["name"] == "Clientes"
        assert [p["name"] for p in svc.rename_profile(profile["id"], "VIP")] == ["VIP"]
        assert [p["name"] for p in svc.profiles("vi")] == ["VIP"] and svc.profiles("zzz") == []
        assert len(svc.create_profile("Otro")) == 2
        assert [p["name"] for p in svc.delete_profile(profile["id"])] == ["Otro"]
        with pytest.raises(UserError, match="ya no existe"):
            svc.load_profile(doc_id, profile["id"])
    finally:
        viewer.close()


# ── Asistente IA (visor) ─────────────────────────────────────────────────────
@pytest.fixture
def isolated_ai_config(tmp_path, monkeypatch):
    """La configuración del agente (claves de API) va a un archivo temporal."""
    from pdf_core.agent import config

    monkeypatch.setattr(config, "_STORE", tmp_path / "config_ia.json")
    return tmp_path / "config_ia.json"


class FakeAgent:
    """Hace de ``PDFAgent`` sin red: recuerda cómo se creó y lo que se le pide."""

    created: list = []

    def __init__(self, pdf_path, api_key, provider, model, ocr_overrides=None):
        self.args = (Path(pdf_path).name, api_key, provider, model, ocr_overrides)
        FakeAgent.created.append(self)

    def chat(self, message, history):
        return f"**Respuesta** a «{message}» con {len(history)} mensajes previos <script>x</script> ![i](http://x/y.png)"

    def summarize(self):
        return "Resumen del agente"

    def extract_key_info(self):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    def suggest_redactions(self, sensitivity):
        return (f"nivel {sensitivity} ```json\n"
                '{"redacciones": [{"texto": "Juan Pérez", "categoria": "nombre", "motivo": "persona", "tipo": "literal"},'
                ' {"texto": "\\\\d{9}", "categoria": "teléfono", "tipo": "patron"}, {"texto": ""}]}\n```')

    def close(self):
        pass


def test_ai_basic_mode_without_agent(tmp_path, isolated_ai_config, monkeypatch):
    pdf = _redact_pdf(tmp_path / "contrato.pdf")
    viewer = ViewerService(FakeHost())
    svc = AiService(viewer)
    monkeypatch.setattr(AiService, "_agent_class", staticmethod(lambda: None))  # sin dependencias del agente
    try:
        doc_id = viewer.open(str(pdf))["id"]
        FakeViewer(viewer, doc_id).sync()  # el visor le da el texto antes de preguntar
        with viewer.document(doc_id) as entry:  # la página escaneada aporta su texto de OCR
            viewer.set_ocr_words(entry, entry.keys[2], [(100, 100, 160, 120, "Factura"), (165, 100, 230, 120, "pagada")])
        config = svc.config()
        assert config["provider"] == "google" and not config["has_key"] and not config["available"]

        user, answer = svc.chat(doc_id, "¿Dónde aparece la factura?")["messages"]
        assert user == {"role": "user", "text": "¿Dónde aparece la factura?"}
        assert answer["mode"] == "básico" and "Pág 3" in answer["text"] and "<strong>Pág 3:</strong>" in answer["html"]
        assert "No se encontraron" in svc.chat(doc_id, "zzzz")["messages"][1]["text"]
        assert "Documento de 4 páginas" in svc.summary(doc_id)["messages"][1]["text"]

        _, found = svc.sensitive(doc_id)["messages"]
        assert {"texto": "juan@correo.com", "categoria": "email", "motivo": "Encontrado en la pág. 2",
                "tipo": "literal"} in found["suggestions"]
        assert len(svc.state(doc_id)["messages"]) == 8
        assert svc.clear(doc_id)["messages"] == []
        with pytest.raises(UserError):
            svc.chat(doc_id, "   ")
        with pytest.raises(UserError):
            svc.sensitive(doc_id, "extrema")
    finally:
        viewer.close()


def test_ai_falls_back_to_basic_mode_without_the_provider_client(tmp_path, isolated_ai_config, monkeypatch):
    """Con clave guardada pero sin el cliente del proveedor, responde en modo básico: no falla."""
    from app.backend.services import ai

    pdf = _redact_pdf(tmp_path / "contrato.pdf")
    viewer = ViewerService(FakeHost())
    svc = AiService(viewer)
    monkeypatch.setattr(ai, "_installed", lambda module: False)
    try:
        svc.set_config("google", "clave-de-prueba")
        doc_id = viewer.open(str(pdf))["id"]
        FakeViewer(viewer, doc_id).sync()
        assert not svc.config()["available"]
        assert svc.chat(doc_id, "Juan")["messages"][1]["mode"] == "básico"

        # Instalado el de otro proveedor: el agente existe, pero este sigue en modo básico.
        monkeypatch.setattr(ai, "_installed", lambda module: module == ai.CLIENTS["openai"])
        assert svc.config()["available"]
        assert svc.chat(doc_id, "Juan")["messages"][1]["mode"] == "básico"
    finally:
        viewer.close()


def test_ai_uses_the_agent_when_configured(tmp_path, isolated_ai_config):
    pdf = _redact_pdf(tmp_path / "contrato.pdf")
    viewer = ViewerService(FakeHost())
    FakeAgent.created = []
    svc = AiService(viewer, agent_factory=FakeAgent)
    try:
        doc_id = viewer.open(str(pdf))["id"]
        FakeViewer(viewer, doc_id).sync()
        with pytest.raises(UserError):
            svc.set_config("anthropic")
        config = svc.set_config("openai", "  sk-123  ", "gpt-4o-mini")
        assert config["provider"] == "openai" and config["has_key"] and config["model"] == "gpt-4o-mini"
        stored = isolated_ai_config.read_text(encoding="utf-8")
        assert "sk-123" not in stored and '"openai_api_key_secret"' in stored  # cifrada, nunca en claro

        first = svc.chat(doc_id, "Hola")["messages"][1]
        assert first["mode"] == "ia" and "0 mensajes previos" in first["text"]
        # El HTML no deja pasar HTML crudo ni carga imágenes.
        assert "<script>" not in first["html"] and "<img" not in first["html"] and "<strong>Respuesta</strong>" in first["html"]
        assert "2 mensajes previos" in svc.chat(doc_id, "Otra")["messages"][1]["text"]
        assert svc.summary(doc_id)["messages"][1]["text"] == "Resumen del agente"
        error = svc.key_data(doc_id)["messages"][1]
        assert error["role"] == "error" and "429" in error["text"]

        found = svc.sensitive(doc_id, "high")["messages"][1]
        assert [(s["texto"], s["tipo"]) for s in found["suggestions"]] == [("Juan Pérez", "literal"), ("\\d{9}", "patron")]
        assert len(FakeAgent.created) == 1 and FakeAgent.created[0].args[:4] == ("contrato.pdf", "sk-123", "openai", "gpt-4o-mini")

        svc.set_config("openai", None, "gpt-4.1")  # al cambiar la configuración se rehace el agente
        svc.chat(doc_id, "De nuevo")
        assert len(FakeAgent.created) == 2 and FakeAgent.created[1].args[3] == "gpt-4.1"
    finally:
        viewer.close()


def test_ai_keys_are_stored_encrypted_and_old_plain_keys_are_migrated(isolated_ai_config):
    import json
    import os

    from pdf_core.agent import config as agent_config
    from pdf_core.agent import keystore

    isolated_ai_config.write_text(json.dumps({"google_api_key": "AIza-antigua", "provider": "google"}), encoding="utf-8")
    assert agent_config.get_api_key("google") == "AIza-antigua"  # una de una versión anterior, en claro
    data = json.loads(isolated_ai_config.read_text(encoding="utf-8"))
    assert "google_api_key" not in data and "AIza-antigua" not in isolated_ai_config.read_text(encoding="utf-8")
    assert keystore.is_protected(data["google_api_key_secret"]) == (os.name == "nt")  # DPAPI en Windows
    assert agent_config.get_api_key("google") == "AIza-antigua"
    agent_config.set_api_key("google", "")
    assert agent_config.get_api_key("google") == "" and "google_api_key_secret" not in json.loads(isolated_ai_config.read_text(encoding="utf-8"))
    # Lo cifrado en otra cuenta u otro equipo no se descifra: se pide de nuevo, sin romper nada.
    isolated_ai_config.write_text(json.dumps({"google_api_key_secret": "dpapi:AAAA"}), encoding="utf-8")
    assert agent_config.get_api_key("google") == ""


def test_ai_errors_never_show_the_api_key(tmp_path, isolated_ai_config, caplog):
    class LeakyAgent:
        def __init__(self, *args, **kw):
            self.key = kw["api_key"]

        def summarize(self):
            raise RuntimeError(f"400 Bad Request for url https://api.example/v1?key={self.key}")

    pdf = _redact_pdf(tmp_path / "contrato.pdf")
    viewer = ViewerService(FakeHost())
    svc = AiService(viewer, agent_factory=LeakyAgent)
    try:
        doc_id = viewer.open(str(pdf))["id"]
        FakeViewer(viewer, doc_id).sync()
        svc.set_config("openai", "sk-secreta-123", "gpt-4o-mini")
        error = svc.summary(doc_id)["messages"][1]
        assert error["role"] == "error" and "400 Bad Request" in error["text"]
        assert "sk-secreta-123" not in error["text"] and "sk-secreta-123" not in caplog.text
    finally:
        viewer.close()


# ── Servicio Seguridad ───────────────────────────────────────────────────────
def test_security_inspect_unlock_and_export(tmp_path):
    locked = _make_pdf(tmp_path / "secreto.pdf", 2, password="clave")
    out = tmp_path / "libre.pdf"
    host = FakeHost(picks=[str(locked)], save_to=str(out))
    svc = SecurityService(host, DocumentService(host))

    info = svc.pick_protected()
    assert info["name"] == "secreto.pdf" and info["protected"] and not info["authenticated"]
    assert info["permissions"] == []  # no se conocen hasta abrirlo

    with pytest.raises(UserError, match="Contraseña incorrecta"):
        svc.unlock(str(locked), "mal")
    with pytest.raises(UserError, match="Ingresa la contraseña"):
        svc.export_unlocked(str(locked), "")
    unlocked = svc.unlock(str(locked), "clave")
    assert unlocked["authenticated"] and host.opened == [str(locked)]
    assert len(unlocked["permissions"]) == 7 and {"label", "allowed"} <= set(unlocked["permissions"][0])

    assert svc.export_unlocked(str(locked), "clave") == str(out)
    assert host.saved_suggestions[-1].endswith("secreto_desbloqueado.pdf")
    with Document.open(out) as doc:
        assert not doc.encrypted and len(doc) == 2


def test_security_protect_uses_checked_permissions(tmp_path, two_pdfs):
    out = tmp_path / "protegido.pdf"
    host = FakeHost(save_to=str(out))
    svc = SecurityService(host, DocumentService(host))
    opts = svc.options()
    assert opts["default_preset"] in {p["key"] for p in opts["presets"]}
    assert [p["key"] for p in opts["permissions"]][0] == "allow_print"

    with pytest.raises(UserError, match="contraseña"):
        svc.protect(str(two_pdfs[0]), "", "", {})
    # Casillas personalizadas (no las de un nivel rápido): solo copiar.
    assert svc.protect(str(two_pdfs[0]), "user", "owner", {"allow_copy": True}) == str(out)
    with pytest.raises(PasswordError):
        Document.open(out)
    with Document.open(out, "user") as doc:
        assert doc.permissions & 16 and not doc.permissions & 4  # copiar sí, imprimir no
    with Document.open(out, "owner") as doc:
        assert doc.permissions == UNRESTRICTED

    # Sin contraseña de propietario se pone una al azar: una vacía quitaría las restricciones.
    svc.protect(str(two_pdfs[0]), "user", "", {"allow_copy": True})
    with pytest.raises(PasswordError):
        Document.open(out, "")
    with Document.open(out, "user") as doc:
        assert not doc.permissions & 4


# ── Servicio Extraer ─────────────────────────────────────────────────────────
def _text_pdf(path: Path, pages: list[str], password: str | None = None) -> Path:
    data = pdf_bytes([[(72, 72, text)] for text in pages])
    path.write_bytes(encrypted(data, password) if password else data)
    return path


class AnsweringHost(FakeHost):
    """Responde las peticiones de contraseña del trabajo como lo haría el diálogo."""

    def __init__(self, service_ref: list, answer: str | None, **kw) -> None:
        super().__init__(**kw)
        self.service_ref = service_ref
        self.answer = answer

    def emit(self, event: str, payload: object = None) -> None:
        super().emit(event, payload)
        if event == "extract:password":
            import threading

            threading.Thread(target=self.service_ref[0].answer_password, args=(self.answer,)).start()


def _events(host: FakeHost, name: str) -> list:
    return [payload for event, payload in host.events if event == name]


def test_extract_smart_search_writes_matching_pages(tmp_path):
    src = _text_pdf(tmp_path / "facturas.pdf", ["portada", "factura total 100", "anexo", "Factura y total"])
    host = FakeHost(picks=[str(src)], folder=str(tmp_path))
    svc = ExtractService(host, DocumentService(host))
    try:
        assert svc.choose_destination()["destination"]["path"] == str(tmp_path)
        assert [t["name"] for t in svc.pick_targets()["targets"]] == ["facturas.pdf"]
        with pytest.raises(UserError, match="palabra clave"):
            svc.start({"mode": "smart", "keywords": "  "})
        assert svc.start({"mode": "smart", "keywords": "factura, total", "match_all": True})["running"]
        assert svc.wait(30)
        finished = _events(host, "extract:finished")[-1]
        assert finished["count"] == 2 and finished["files"] == 1
        assert sorted(m["page"] for m in _events(host, "extract:match")) == [2, 4]
        assert len(page_texts(finished["path"])) == 2
        assert svc.state()["last_output"] == finished["path"] and not svc.state()["running"]
        assert any(log["tone"] == "success" for log in _events(host, "extract:log"))
    finally:
        svc.close()


def test_extract_range_asks_password_mid_job(tmp_path):
    locked = _text_pdf(tmp_path / "privado.pdf", ["uno", "dos", "tres"], password="clave")
    ref: list = []
    host = AnsweringHost(ref, "clave", picks=[str(locked)], folder=str(tmp_path))
    svc = ExtractService(host, DocumentService(host))
    ref.append(svc)
    try:
        svc.choose_destination()
        svc.pick_targets()
        svc.start({"mode": "range", "range": "2-3"})
        assert svc.wait(30)
        assert _events(host, "extract:password")[0]["name"] == "privado.pdf"
        finished = _events(host, "extract:finished")[-1]
        assert finished["count"] == 2
        assert page_texts(finished["path"]) == ["dos", "tres"]
    finally:
        svc.close()


def test_quit_warns_about_running_extraction(tmp_path):
    import time

    from app.backend.services import quit_warnings

    locked = _text_pdf(tmp_path / "privado.pdf", ["uno"], password="clave")
    host = FakeHost(picks=[str(locked)], folder=str(tmp_path))
    _, services = build_registry(host, Settings(tmp_path / "s.json"))
    svc = services["extract"]
    try:
        assert quit_warnings(services) is None
        svc.choose_destination()
        svc.pick_targets()
        svc.start({"mode": "range", "range": "1"})
        deadline = time.monotonic() + 10
        while not _events(host, "extract:password") and time.monotonic() < deadline:
            time.sleep(0.05)
        # El trabajo espera la contraseña: salir lo cancelaría.
        assert quit_warnings(services) == {"documents": [], "jobs": ["Extracción de páginas"]}
        svc.cancel()
        assert svc.wait(10)
        assert quit_warnings(services) is None
    finally:
        svc.close()


def test_extract_skipped_password_and_wrong_answer(tmp_path):
    locked = _text_pdf(tmp_path / "privado.pdf", ["uno"], password="clave")
    ref: list = []
    host = AnsweringHost(ref, None, picks=[str(locked)], folder=str(tmp_path))  # el usuario cancela el diálogo
    svc = ExtractService(host, DocumentService(host))
    ref.append(svc)
    try:
        svc.choose_destination()
        svc.pick_targets()
        svc.start({"mode": "range", "range": "1"})
        assert svc.wait(30)
        assert _events(host, "extract:finished")[-1]["count"] == 0
        assert any("omitido" in log["text"] for log in _events(host, "extract:log"))
        # Fuera de un trabajo, una respuesta se ignora; dentro, una contraseña errónea se rechaza.
        svc.answer_password("lo que sea")
        svc._pending_path = str(locked)
        with pytest.raises(UserError, match="Contraseña incorrecta"):
            svc.answer_password("mal")
    finally:
        svc._pending_path = None
        svc.close()


# ── Ayuda y diagnóstico ──────────────────────────────────────────────────────
def test_help_renders_markdown_safely(tmp_path):
    docs = tmp_path / "ayuda"
    docs.mkdir()
    (docs / "2_SEGUNDO.md").write_text("Texto con <script>alert(1)</script> y [enlace](https://x.org)", encoding="utf-8")
    (docs / "1_PRIMERO.md").write_text("## Sección\n\n| a | b |\n|---|---|\n| 1 | 2 |", encoding="utf-8")
    svc = HelpService((tmp_path / "no_existe", docs))
    assert svc.documents() == [
        {"file": "1_PRIMERO.md", "title": "1 PRIMERO"},
        {"file": "2_SEGUNDO.md", "title": "2 SEGUNDO"},
    ]
    first = svc.document("1_PRIMERO.md")
    assert first["title"] == "1 PRIMERO" and "<table>" in first["html"] and "Manual de Usuario" in first["html"]
    second = svc.document("2_SEGUNDO.md")["html"]
    assert "<script>" not in second and "&lt;script&gt;" in second and 'href="https://x.org"' in second
    with pytest.raises(UserError):
        svc.document("../../secreto.md")  # solo los nombres de la lista


def test_help_inlines_local_images_only_inside_assets(tmp_path):
    assets = tmp_path / "assets"
    (assets / "ayuda").mkdir(parents=True)
    (assets / "ayuda_img").mkdir()
    (assets / "ayuda_img" / "a.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "secreto.png").write_bytes(b"no")
    (assets / "ayuda" / "doc.md").write_text(
        "![uno](/ayuda_img/a.png) ![dos](/../secreto.png) ![tres](/ayuda_img/falta.png)", encoding="utf-8"
    )
    html = HelpService((assets / "ayuda",)).document("doc.md")["html"]
    assert 'src="data:image/png;base64,' in html  # imagen local incrustada
    assert 'src="/../secreto.png"' in html  # fuera de la carpeta de recursos: no se lee
    assert 'src="/ayuda_img/falta.png"' in html  # inexistente: se deja tal cual


def test_app_about_and_diagnostics_log(tmp_path):
    log = tmp_path / "app.log"
    svc = AppService(FakeHost(), Settings(tmp_path / "s.json"), log_file=log)
    assert svc.diagnostics_log() == "No hay registro de depuración disponible."
    log.write_text("linea 1\nlinea 2\n", encoding="utf-8")
    assert svc.diagnostics_log().endswith("linea 2\n")
    about = svc.about()
    assert about["pdfium"] == str(pypdfium2.PDFIUM_INFO.build) and about["pywebview"] != "?"
    assert about["app"].endswith("-web")


# ── Frontend coherente con el backend ────────────────────
_ICON_USE = re.compile(r"""(?:data-icon=|\bic\(|setIcon\([\w.]+,\s*|\bicon:\s*)["']([a-z0-9-]+)["']""")
_RPC_USE = re.compile(r"""\bcall(?:<[^>]*>)?\(\s*'([a-z_]+\.[a-z_]+)'""")  # también call<Tipo>('…')
# Svelte: <Icon name="save" />, <Icon name={dark ? 'sun' : 'moon'} /> y fragmentos que
# reciben el icono como primer argumento: {@render button('save', 'Guardar', …)}.
_SVELTE_ICON = re.compile(r"""<Icon\b[^>]*?\bname=(?:"([a-z0-9-]+)"|\{([^}]*)\})""")
_SVELTE_RENDER_ICON = re.compile(r"""\{@render \w+\(\s*'([a-z0-9-]+)'""")
UI_SRC_DIR = UI_DIR / "src"


def _frontend_sources() -> str:
    """Código de la interfaz (app/ui/src)."""
    files = [*UI_SRC_DIR.rglob("*.js"), *UI_SRC_DIR.rglob("*.ts"), *UI_SRC_DIR.rglob("*.svelte")]
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def _svelte_icons(src: str) -> set[str]:
    used = set(_SVELTE_RENDER_ICON.findall(src))
    for literal, expr in _SVELTE_ICON.findall(src):
        # En un ternario solo cuentan los resultados, no la condición (tone === 'danger' ? …).
        used |= {literal} if literal else set(re.findall(r"'([a-z0-9-]+)'", expr.partition("?")[2] or expr))
    return used


def test_every_icon_used_in_the_frontend_exists():
    names = set(json.loads((UI_SRC_DIR / "assets" / "icons.json").read_text(encoding="utf-8")))
    src = _frontend_sources()
    assert {"file-text", "sun", "moon"} <= _svelte_icons(src), "el patrón de Svelte no encontró los iconos de App.svelte"
    used = set(_ICON_USE.findall(src)) | _svelte_icons(src)
    assert used, "el patrón no encontró ningún icono"
    assert used - names == set()


def test_every_rpc_called_by_the_frontend_exists(tmp_path):
    reg, services = build_registry(FakeHost(), Settings(tmp_path / "s.json"))
    src = _frontend_sources()
    called = set(_RPC_USE.findall(src))
    # Cualquier 'servicio.metodo' escrito en el frontend (p. ej. update('extract.clear_targets')).
    services = {m.split(".")[0] for m in reg.methods()}
    called |= {f"{svc}.{m}" for svc, m in re.findall(r"""['"]([a-z]+)\.([a-z_]+)['"]""", src) if svc in services}
    # Merge.svelte llama a request('metodo') → "merge.metodo"; RecentFiles.svelte, run('metodo') → "documents.metodo"
    called |= {f"merge.{m}" for m in re.findall(r"""(?:request|update|load)\('([a-z_]+)'""", src)}
    called |= {f"documents.{m}" for m in re.findall(r"""\brun\('([a-z_]+)'""", src)}
    assert called - set(reg.methods()) == set()


# ── Caché de WebView2 ────────────────────────────────────────────────────────
def test_webview_cache_is_discarded_when_the_frontend_changes(tmp_path):
    import os

    from app.webview_cache import discard_stale_cache

    frontend = tmp_path / "frontend"
    (frontend / "js").mkdir(parents=True)
    module = frontend / "js" / "ui.js"
    module.write_text("export const a = 1;", encoding="utf-8")
    storage = tmp_path / "webview"
    cache = storage / "EBWebView" / "Default" / "Cache"
    prefs = storage / "EBWebView" / "Default" / "Preferences"

    def fill_cache():
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "data_0").write_text("viejo", encoding="utf-8")
        prefs.write_text("{}", encoding="utf-8")

    fill_cache()
    assert discard_stale_cache(frontend, storage)  # primer arranque
    assert not cache.exists() and prefs.exists()  # solo la caché

    fill_cache()
    assert not discard_stale_cache(frontend, storage)  # sin cambios: se conserva
    assert cache.exists()

    module.write_text("export const a = 1; export const askText = 2;", encoding="utf-8")
    os.utime(module, ns=(1, 2_000_000_000_000_000_000))
    assert discard_stale_cache(frontend, storage)  # frontend nuevo: caché fuera
    assert not cache.exists()


def test_host_opens_only_dropped_pdfs(tmp_path):
    from app.host import WebviewHost

    pdf = _make_pdf(tmp_path / "soltado.pdf", 1)
    (tmp_path / "nota.txt").write_text("x", encoding="utf-8")
    opened: list[list[str]] = []
    host = WebviewHost()
    host._on_drop_files = opened.append
    files = [{"name": "soltado.pdf", "pywebviewFullPath": str(pdf)},
             {"name": "nota.txt", "pywebviewFullPath": str(tmp_path / "nota.txt")},
             {"name": "falta.pdf", "pywebviewFullPath": str(tmp_path / "falta.pdf")},
             {"name": "sin_ruta.pdf"}]
    host._on_drop({"dataTransfer": {"files": files}})
    host._on_drop({"dataTransfer": {"files": []}})  # mover miniaturas también llega aquí: se ignora
    assert opened == [[str(pdf)]]


def test_single_instance_forwards_pdfs_to_the_first_window(tmp_path):
    import threading
    import uuid

    from app.single_instance import SingleInstance

    pdf = _make_pdf(tmp_path / "abrir_con.pdf", 1)
    name = f"pdfm_test_{uuid.uuid4().hex[:8]}"
    first, second = SingleInstance(name), SingleInstance(name)
    received: list[list[str]] = []
    done = threading.Event()
    try:
        assert first.acquire([])
        first.listen(lambda paths: (received.append(paths), done.set()))
        assert not second.acquire([str(pdf), str(tmp_path / "no_existe.pdf"), 42])  # va a la primera
        assert done.wait(5)
        assert received == [[str(pdf.resolve())]]
        done.clear()
        assert not SingleInstance(name).acquire([])  # volver a abrir la app: lista vacía
        assert done.wait(5) and received[-1] == []
    finally:
        first.close()
    assert SingleInstance(name).acquire([])  # cerrada la primera, otra puede ser la principal


def test_single_instance_never_unpickles_what_it_receives(tmp_path):
    """Lo que llega por la tubería es JSON: un objeto de pickle no se ejecuta, se descarta."""
    import pickle
    import threading
    import uuid
    from multiprocessing.connection import Client

    from app.single_instance import SingleInstance

    class Boom:
        def __reduce__(self):
            return (open, (str(tmp_path / "ejecutado.txt"), "w"))

    name = f"pdfm_test_{uuid.uuid4().hex[:8]}"
    first = SingleInstance(name)
    received: list[list[str]] = []
    done = threading.Event()
    try:
        assert first.acquire([])
        first.listen(lambda paths: (received.append(paths), done.set()))
        with Client(first._address, first._family, authkey=first._authkey) as conn:
            conn.send_bytes(pickle.dumps([Boom()]))
        with pytest.raises(OSError), Client(first._address, first._family, authkey=first._authkey) as conn:
            conn.send_bytes(b"[" * (300 * 1024))  # más largo que el límite: corta la conexión
        assert not SingleInstance(name).acquire([])  # y después, una instancia normal
        assert done.wait(5) and received == [[]]
        assert not (tmp_path / "ejecutado.txt").exists()
    finally:
        first.close()


def test_app_runs_ready_callbacks_once(tmp_path):
    host = FakeHost()
    svc = AppService(host, Settings(tmp_path / "s.json"))
    calls = []
    svc.when_ready(lambda: calls.append("abrir"))
    svc.ready()
    svc.ready()
    assert calls == ["abrir"]


def test_frontend_url_chooses_the_interface(tmp_path, monkeypatch):
    import app.main as app_main

    storage = tmp_path / "webview"
    monkeypatch.setattr(app_main.ui_dev, "responds", lambda url: False)
    with pytest.raises(SystemExit, match="--dev"):  # Vite apagado: se avisa en vez de abrir una ventana vacía
        app_main.frontend_url("http://localhost:5173", storage)
    monkeypatch.setattr(app_main.ui_dev, "responds", lambda url: True)
    assert app_main.frontend_url("http://localhost:5173", storage) == "http://localhost:5173"
    dist = tmp_path / "dist"
    monkeypatch.setattr(app_main, "UI_DIST_DIR", dist)
    with pytest.raises(SystemExit, match="pnpm build"):  # sin compilar: se avisa de cómo hacerlo
        app_main.frontend_url(None, storage)
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    assert app_main.frontend_url(None, storage) == str(dist / "index.html")


def test_ui_needs_build_only_when_sources_are_newer(tmp_path):
    import os

    from app import ui_dev

    ui = tmp_path / "ui"
    (ui / "src" / "styles").mkdir(parents=True)
    (ui / "src" / "App.svelte").write_text("<p></p>", encoding="utf-8")
    (ui / "src" / "styles" / "tokens.css").write_text(":root {}", encoding="utf-8")
    assert ui_dev.needs_build(ui)  # sin compilar

    index = ui / "dist" / "index.html"
    index.parent.mkdir()
    index.write_text("<!doctype html>", encoding="utf-8")
    now = index.stat().st_mtime
    for source in (ui / "src" / "App.svelte", ui / "src" / "styles" / "tokens.css"):
        os.utime(source, (now - 10, now - 10))
    assert not ui_dev.needs_build(ui)  # compilación al día

    os.utime(ui / "src" / "styles" / "tokens.css", (now + 10, now + 10))
    assert ui_dev.needs_build(ui)  # cambió un estilo
    assert not ui_dev.needs_build(tmp_path / "empaquetado")  # sin fuentes (ejecutable): nunca


# ── Datos para el visor con PDFium ───────────────────────────────────────────
def test_document_url_is_the_file_with_its_password(tmp_path):
    with Document.new() as doc:
        for _ in range(3):
            add_page(doc)
        add_annot(doc[0], "Square", Rect(50, 50, 150, 150))
        data = doc.to_bytes()
    pdf = tmp_path / "anotado.pdf"
    pdf.write_bytes(encrypted(data, "clave"))
    svc = ViewerService(FakeHost())
    info = svc.open(str(pdf), "clave")
    viewer = FakeViewer(svc, info["id"])
    viewer.reshape([["rotate", [1], 1]], [1, 2, 3])

    result = svc.document_url(info["id"])
    assert result["keys"] == info["keys"]  # el archivo en disco, con las páginas que tiene
    assert result["password"] == "clave"  # sigue cifrado: la copia que vuelve conserva el cifrado
    data = base64.b64decode(result["url"].split(",", 1)[1])
    assert data == pdf.read_bytes()
    with pytest.raises(PasswordError):
        Document.open(data)
    with Document.open(data, "clave") as doc:
        assert annots(doc[0]) == ["Square"]  # las anotaciones las edita EmbedPDF
    viewer.save()
    assert svc.document_url(info["id"])["keys"] == ["1:0:0", "2:90:0", "3:0:0"]  # ya guardado
    svc.close()
    with Document.open(pdf, "clave") as saved:
        assert saved.encrypted and [p.rotation for p in saved] == [0, 90, 0]


def test_document_url_gives_the_ocr_words_for_the_viewer_to_write(tmp_path):
    pdf = _blank_pdf(tmp_path / "escaneo.pdf", 2, native={0: "Nativo"})
    svc = ViewerService(FakeHost())
    info = svc.open(str(pdf))
    with svc.document(info["id"]) as entry:
        svc.set_ocr_words(entry, info["keys"][1], [(100, 300, 220, 320, "Hola ñandú")])
    served = svc.document_url(info["id"])
    assert served["ocr"] == [{"index": 1, "words": [(100, 300, 220, 320, "Hola ñandú")]}]
    with _served(svc, info["id"]) as doc:
        assert "Hola" not in doc[1].text()  # el PDF va sin él: lo escribe el visor
    assert "ñandú" in _served_text(svc, info["id"])[1]
    svc.close()


def test_byte_server_serves_each_item_once(monkeypatch):
    import urllib.error
    import urllib.request

    from app import byte_server

    server = byte_server.ByteServer()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        url = server.share(b"%PDF-1.7 datos", "application/pdf")
        assert url.startswith("http://127.0.0.1:")
        with opener.open(url, timeout=5) as res:
            assert res.read() == b"%PDF-1.7 datos"
            assert res.headers["Content-Type"] == "application/pdf"
        with pytest.raises(urllib.error.HTTPError):  # un solo uso
            opener.open(url, timeout=5)
        with pytest.raises(urllib.error.HTTPError):  # código desconocido
            opener.open(url.rsplit("/", 1)[0] + "/otro", timeout=5)
        stale = server.share(b"x", "text/plain")
        monkeypatch.setattr(byte_server, "TTL", -1)  # caducado
        with pytest.raises(urllib.error.HTTPError):
            opener.open(stale, timeout=5)
    finally:
        server.close()


def test_byte_server_only_answers_its_own_address_and_limits_uploads(monkeypatch):
    import http.client

    from app import byte_server

    server = byte_server.ByteServer()
    try:
        url = server.share(b"secreto", "application/pdf")
        port, token = int(url.split(":")[2].split("/")[0]), url.rsplit("/", 1)[1]

        def request(method: str, path: str, host: str, body: bytes | None = None, length: str | None = None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.putrequest(method, path, skip_host=True)
            conn.putheader("Host", host)
            if body is not None or length is not None:
                conn.putheader("Content-Length", length or str(len(body or b"")))
            conn.endheaders(body)
            response = conn.getresponse()
            data = response.read()
            conn.close()
            return response, data

        # Una web cuyo dominio apunta a 127.0.0.1 (DNS rebinding) no recibe el dato, ni lo gasta.
        assert request("GET", f"/{token}", "malo.example:80")[0].status == 403
        response, data = request("GET", f"/{token}", f"127.0.0.1:{port}")
        assert response.status == 200 and data == b"secreto" and response.headers["X-Content-Type-Options"] == "nosniff"

        upload = server.expect().rsplit("/", 1)[1]
        assert request("POST", f"/up/{upload}", "malo.example:80", b"x")[0].status == 403
        monkeypatch.setattr(byte_server, "MAX_UPLOAD", 4)
        assert request("POST", f"/up/{upload}", f"127.0.0.1:{port}", length="999")[0].status == 413
        assert request("POST", f"/up/{upload}", f"127.0.0.1:{port}", length="no")[0].status == 400
        assert request("POST", f"/up/{upload}", f"127.0.0.1:{port}", b"pdf")[0].status == 204
        assert server.received(f"http://127.0.0.1:{port}/up/{upload}") == b"pdf"
    finally:
        server.close()


def test_only_web_and_mail_links_open_outside():
    from app.backend.host import is_external_url

    for url in ["https://example.com/a?b=1", "http://localhost:8000", "mailto:soporte@example.com", " https://x.org "]:
        assert is_external_url(url), url
    for url in ["javascript:alert(1)", "file:///C:/Windows/System32/calc.exe", r"C:\Windows\notepad.exe", "https://",
                "data:text/html,<script>", "ms-settings:", "https://ok.com/\r\nX", r"\\servidor\recurso", 42,
                "https://" + "a" * 3000]:
        assert not is_external_url(url), url
