"""La versión de navegador sin navegador: su ``Host``, sus archivos y sus hilos."""
import json
import threading

import numpy as np
import pytest

from app.browser import background, onnx
from app.browser.files import Files
from app.browser.host import BrowserHost


class FakeChannel:
    """La ventana: ``window`` son los archivos que tiene (ruta -> contenido)."""

    def __init__(self):
        self.replies = {}
        self.events = []
        self.written = {}  # lo que entrega flush (Python tiene copia)
        self.kept = {}  # lo que escribe write_file (Python no tiene copia)
        self.asked = []
        self.window = {}

    def ask(self, kind, payload, data=None):
        request = json.loads(payload)
        self.asked.append((kind, request, data))
        if kind == "read":
            found = [path for path in request["paths"] if path in self.window]
            files = [{"path": path, "size": len(self.window[path])} for path in found]
            return json.dumps({"files": files}), b"".join(self.window[path] for path in found)
        if kind == "size":
            data = self.window.get(request["path"])
            return json.dumps(None if data is None else len(data)), b""
        if kind == "url":
            return json.dumps(f"blob:{request['path']}" if request["path"] in self.window else None), b""
        value, reply = self.replies[kind]
        return json.dumps(value), reply

    def emit(self, event, payload):
        self.events.append((event, json.loads(payload)))

    def share(self, data, content_type):
        return f"blob:{len(data)}"

    def saved(self, path, data):
        self.written[path] = data

    def write(self, path, data):
        self.kept[path] = data
        self.window[path] = data


@pytest.fixture
def host(tmp_path):
    return BrowserHost(FakeChannel(), Files(tmp_path))


def _pick(host, files):
    """El usuario elige ``files`` (ruta -> contenido): la ventana se los queda."""
    host._channel.window.update(files)
    host._channel.replies["pick"] = (list(files), b"")


def test_picked_files_are_copied_and_not_reported_as_changed(host, tmp_path):
    first, second = str(tmp_path / "1" / "a.pdf"), str(tmp_path / "2" / "b.pdf")
    _pick(host, {first: b"aaa", second: b"bb"})
    assert host.pick_pdfs() == [first, second]
    assert (tmp_path / "1" / "a.pdf").read_bytes() == b"aaa"
    assert (tmp_path / "2" / "b.pdf").read_bytes() == b"bb"
    host.flush()
    assert host._channel.written == {}


def test_a_cancelled_pick_gives_nothing(host):
    host._channel.replies["pick"] = ([], b"")
    assert host.pick_pdfs() == []
    assert host.pick_pdf() is None


def test_what_a_service_writes_reaches_the_window_once(host, tmp_path):
    path = str(tmp_path / "3" / "salida.pdf")
    host._channel.replies["save"] = (path, b"")
    dest = host.save_pdf("/files/1/entrada_protegido.pdf")
    assert host._channel.asked[-1][1] == {"name": "entrada_protegido.pdf", "kind": "pdf"}
    with open(dest, "wb") as f:
        f.write(b"pdf")
    host.flush()
    host.flush()
    assert host._channel.written == {path: b"pdf"}


def test_saving_over_a_picked_file_reaches_the_window(host, tmp_path):
    path = tmp_path / "1" / "a.pdf"
    _pick(host, {str(path): b"a"})
    host.pick_pdf()
    path.write_bytes(b"cambiado")
    host.flush()
    assert host._channel.written == {str(path): b"cambiado"}


def test_cancelled_dialogs_return_none(host):
    host._channel.replies["save"] = (None, b"")
    host._channel.replies["folder"] = (None, b"")
    assert host.save_pdf("x.pdf") is None
    assert host.pick_folder() is None


def test_picked_folder_brings_its_pdfs(host, tmp_path):
    folder = tmp_path / "9"
    item = str(folder / "a.pdf")
    host._channel.window[item] = b"a"
    host._channel.replies["folder"] = ({"path": str(folder), "files": [item]}, b"")
    assert host.pick_folder() == str(folder)
    assert (folder / "a.pdf").read_bytes() == b"a"


def test_an_empty_picked_folder_exists(host, tmp_path):
    folder = tmp_path / "9"
    host._channel.replies["folder"] = ({"path": str(folder), "files": []}, b"")
    assert host.pick_folder() == str(folder)
    assert folder.is_dir()


def test_output_folder_says_what_it_is_for(host, tmp_path):
    host._channel.replies["folder"] = ({"path": str(tmp_path / "9"), "files": []}, b"")
    host.pick_folder()
    host.pick_output_folder()
    assert [asked[1] for asked in host._channel.asked] == [{"output": False}, {"output": True}]


def test_documents_for_the_viewer_stay_in_the_window(host, tmp_path):
    path = str(tmp_path / "1" / "a.pdf")
    _pick(host, {path: b"pdf"})
    assert host.pick_documents() == [path]
    assert not (tmp_path / "1").exists()  # sin copia en Python
    assert host.file_size(path) == 3
    assert host.read_file(path) == b"pdf"
    assert host.file_url(path) == f"blob:{path}"  # la URL es del archivo de la ventana


def test_the_viewer_writes_its_documents_in_the_window(host, tmp_path):
    path = str(tmp_path / "1" / "a.pdf")
    _pick(host, {path: b"pdf"})
    host.pick_documents()
    host.write_file(path, b"guardado")
    host.flush()
    assert host._channel.kept == {path: b"guardado"}
    assert host._channel.written == {}  # flush no lo entrega otra vez
    assert host.read_file(path) == b"guardado"
    assert not (tmp_path / "1").exists()


def test_a_document_python_has_is_read_and_written_there(host, tmp_path):
    """El resultado de una herramienta abierto en el visor."""
    path = tmp_path / "3" / "combinado.pdf"
    path.parent.mkdir()
    path.write_bytes(b"pdf")
    assert host.read_file(str(path)) == b"pdf"
    assert host.file_size(str(path)) == 3
    assert host.file_url(str(path)) == "blob:3"
    host.write_file(str(path), b"guardado")
    host.flush()
    assert host._channel.written == {str(path): b"guardado"}
    assert host._channel.kept == {}


def test_a_missing_document_is_not_found(host, tmp_path):
    path = str(tmp_path / "1" / "otro.pdf")
    assert host.file_size(path) is None
    with pytest.raises(FileNotFoundError):
        host.read_file(path)
    with pytest.raises(FileNotFoundError):
        host.file_url(path)


def test_engine_tasks_go_to_the_window(host):
    host._channel.replies["engine"] = (None, b"resultado")
    assert host.run_engine("redact", b"pdf", {"password": None}) == b"resultado"
    assert host._channel.asked[-1] == ("engine", {"task": "redact", "args": {"password": None}}, b"pdf")


def test_engine_errors_are_raised(host):
    host._channel.replies["engine"] = ({"error": "falló"}, b"")
    with pytest.raises(RuntimeError, match="falló"):
        host.run_engine("redact", b"pdf", {})


def test_uploads_are_read_once(host):
    url = host.upload_url()
    assert host.uploaded(url) is None
    host.receive(url, b"datos")
    assert host.uploaded(url) == b"datos"
    assert host.uploaded(url) is None


def test_only_web_links_are_opened(host):
    host.open_url("https://example.com")
    host.open_url("file:///c:/secreto.txt")
    assert host._channel.events == [("browser:open-url", "https://example.com")]


@pytest.fixture
def deferred(monkeypatch):
    """Los hilos del navegador, solo durante la prueba."""
    polls = []

    def poll(ms):
        polls.append(ms)
        return False

    monkeypatch.setattr(background, "_poll", poll)
    background._pending.clear()
    yield polls
    background._pending.clear()


def test_a_thread_runs_after_the_call_that_starts_it(deferred):
    ran = []
    thread = background.DeferredThread(target=lambda: ran.append(1))
    thread.start()
    assert ran == [] and thread.is_alive()
    assert background.run_pending() is True
    assert ran == [1] and not thread.is_alive()
    assert background.run_pending() is False


def test_join_runs_a_waiting_thread(deferred):
    ran = []
    thread = background.DeferredThread(target=lambda: ran.append(1))
    thread.start()
    thread.join()
    assert ran == [1]
    assert background.run_pending() is False


def test_a_failing_thread_does_not_stop_the_next(deferred):
    ran = []
    background.DeferredThread(target=lambda: 1 / 0).start()
    background.DeferredThread(target=lambda: ran.append(1)).start()
    background.run_pending()
    assert ran == [1]


def test_pump_only_works_during_a_job(deferred):
    background.pump()
    assert deferred == []
    background.DeferredThread(target=background.pump).start()
    background.run_pending()
    assert deferred == [0]


def test_event_wait_serves_calls_until_it_is_set(monkeypatch):
    event = background.PumpedEvent()
    calls = []

    def poll(ms):
        calls.append(ms)
        if len(calls) == 3:
            event.set()
        return True

    monkeypatch.setattr(background, "_poll", poll)
    assert event.wait() is True
    assert len(calls) == 3


def test_event_wait_gives_up_after_its_timeout(monkeypatch):
    monkeypatch.setattr(background, "_poll", lambda ms: False)
    assert background.PumpedEvent().wait(0.01) is False


def test_install_replaces_threads(monkeypatch):
    for name in ("Thread", "Timer", "Event"):
        monkeypatch.setattr(threading, name, getattr(threading, name))
    monkeypatch.setattr(background, "_poll", background._poll)
    background.install(lambda ms: False)
    assert threading.Thread is background.DeferredThread
    threading.Timer(5, print).start()  # no se dispara


def test_onnx_session_sends_tensors_and_reads_the_output():
    asked = []

    def ask(kind, payload, data):
        asked.append((kind, payload, data))
        if data is None:
            return {"shape": None}, b""
        return {"shape": [1, 2]}, np.array([[0.25, 0.75]], np.float32).tobytes()

    session = onnx.session_class(ask)("/modelos/rec.onnx", onnx.SessionOptions(), providers=["CPUExecutionProvider"])
    assert asked[0] == ("onnx", {"model": "rec.onnx"}, None)
    x = np.zeros((1, 3), np.float64)
    (output,) = session.run(None, {"x": x})
    assert output.tolist() == [[0.25, 0.75]] and output.dtype == np.float32
    assert asked[1][1] == {"model": "rec.onnx", "input": "x", "shape": [1, 3]}
    assert asked[1][2] == np.zeros((1, 3), np.float32).tobytes()


def test_onnx_errors_are_raised():
    def ask(_kind, _payload, _data):
        return {"error": "sin memoria"}, b""

    with pytest.raises(RuntimeError, match="sin memoria"):
        onnx.session_class(ask)("rec.onnx")
