"""Modelos del OCR: los instalados con la app o, si faltan, descargados (y comprobados) al usarlos."""

from __future__ import annotations

import hashlib
import io
import urllib.error
from pathlib import Path

import pytest

import app  # noqa: F401  (añade src/ al sys.path)
from app import APP_VERSION, GITHUB_REPO
from app.backend.rpc import UserError
from app.backend.services.ocr_models import OCR_DOWNLOAD, SOURCES, OcrModels
from pdf_core.ocr import models


def _fake(name: str, content: bytes) -> models.Model:
    return models.Model(name, hashlib.sha256(content).hexdigest(), len(content))


PRIMARY, BACKUP = "https://primero/{name}.onnx", "https://respaldo/{name}.onnx"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    bundled, user = tmp_path / "app" / "ocr_models", tmp_path / "home" / "ocr_models"
    bundled.mkdir(parents=True)
    monkeypatch.setattr(models, "BUNDLED_DIR", bundled)
    monkeypatch.setattr(models, "USER_DIR", user)
    return bundled, user


def test_the_expected_models_are_the_ones_in_assets():
    """Solo se acepta lo que lleva el instalador (misma suma y tamaño que assets/ocr_models)."""
    for model in models.MODELS.values():
        shipped = Path(__file__).resolve().parents[1] / "src" / "assets" / "ocr_models" / f"{model.name}.onnx"
        assert shipped.stat().st_size == model.size
        assert hashlib.sha256(shipped.read_bytes()).hexdigest() == model.sha256


def test_the_app_downloads_from_its_own_release_and_then_from_the_repository():
    """Del repositorio y de la versión de la app; nunca de terceros."""
    tag = f"v{APP_VERSION}"
    assert SOURCES == (
        f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/{{name}}.onnx",
        f"https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}/src/assets/ocr_models/{{name}}.onnx",
    )
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-web.yml").read_text(encoding="utf-8")
    assert "src/assets/ocr_models/*.onnx" in workflow  # la Release de cada versión los lleva


def test_bundled_models_win_and_missing_ones_are_looked_for_in_the_user_folder(dirs, monkeypatch):
    bundled, user = dirs
    monkeypatch.setattr(models, "MODELS", {"a": _fake("a", b"A"), "b": _fake("b", b"B")})
    (bundled / "a.onnx").write_bytes(b"A")
    assert models.model_file("a") == bundled / "a.onnx"
    assert models.model_file("b") == user / "b.onnx"
    assert [m.name for m in models.missing()] == ["b"]
    user.mkdir(parents=True)
    (user / "b.onnx").write_bytes(b"B")
    assert models.missing() == []


def test_download_checks_the_sum_and_reports_progress(dirs):
    _, user = dirs
    good, bad = _fake("good", b"x" * 600_000), _fake("bad", b"y" * 10)
    served = {PRIMARY.format(name="good"): b"x" * 600_000, PRIMARY.format(name="bad"): b"distinto"}
    seen: list[tuple[int, int]] = []
    models.download([good], [PRIMARY], lambda done, total: seen.append((done, total)),
                    opener=lambda url, timeout: _Response(served[url]))
    assert (user / "good.onnx").read_bytes() == b"x" * 600_000
    assert seen[-1] == (600_000, 600_000) and len(seen) > 1
    with pytest.raises(models.DownloadError, match="no es el esperado"):
        models.download([bad], [PRIMARY], opener=lambda url, timeout: _Response(served[url]))
    assert not (user / "bad.onnx").exists() and not list(user.glob("*.part"))


def test_download_without_connection_leaves_nothing(dirs):
    _, user = dirs

    def offline(url, timeout):
        raise urllib.error.URLError("sin conexión")

    with pytest.raises(models.DownloadError, match="sin conexión"):
        models.download([_fake("m", b"M")], [PRIMARY, BACKUP], opener=offline)
    assert not list(user.glob("*"))


def test_download_falls_back_to_the_next_source(dirs):
    """Si la Release no los tiene (404) o están mal, se prueba el siguiente origen."""
    _, user = dirs
    a, b = _fake("a", b"A" * 10), _fake("b", b"B" * 10)
    asked = []

    def opener(url, timeout):
        asked.append(url)
        if url == PRIMARY.format(name="a"):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        if url == PRIMARY.format(name="b"):
            return _Response(b"roto")
        return _Response(b"A" * 10 if "/a." in url else b"B" * 10)

    seen = []
    models.download([a, b], [PRIMARY, BACKUP], lambda done, total: seen.append((done, total)), opener=opener)
    assert (user / "a.onnx").read_bytes() == b"A" * 10 and (user / "b.onnx").read_bytes() == b"B" * 10
    assert asked == [PRIMARY.format(name="a"), BACKUP.format(name="a"), PRIMARY.format(name="b"), BACKUP.format(name="b")]
    assert seen[-1] == (20, 20)


class _Host:
    def __init__(self):
        self.events: list[tuple[str, object]] = []

    def emit(self, event, payload=None):
        self.events.append((event, payload))


def test_ocr_models_download_once_and_tell_the_window(dirs, monkeypatch):
    model = _fake("m", b"M" * 1000)
    monkeypatch.setattr(models, "MODELS", {"m": model})
    calls = []
    real = models.download
    monkeypatch.setattr(models, "download", lambda todo, sources, progress: (calls.append(sources), real(
        todo, sources, progress, opener=lambda url, timeout: _Response(b"M" * 1000))))
    host = _Host()
    OcrModels(host).ensure()
    OcrModels(host).ensure()  # ya están: no vuelve a descargar
    assert calls == [SOURCES]
    payloads = [p for e, p in host.events if e == OCR_DOWNLOAD]
    assert payloads[0] == {"percent": 0, "megabytes": 0} and payloads[-1] == {"done": True}
    assert {"percent": 100} in payloads


def test_ocr_models_failure_is_a_user_error(dirs, monkeypatch):
    monkeypatch.setattr(models, "MODELS", {"m": _fake("m", b"M")})

    def offline(todo, sources, progress):
        raise models.DownloadError("sin conexión")

    monkeypatch.setattr(models, "download", offline)
    host = _Host()
    with pytest.raises(UserError) as ex:
        OcrModels(host).ensure()
    assert ex.value.code == "ocr_download" and "conexión a internet" in str(ex.value)
    assert host.events[-1] == (OCR_DOWNLOAD, {"failed": True})


def test_the_ocr_services_ask_for_the_models_before_loading_them(monkeypatch):
    from app.backend.services.extract import ExtractService
    from app.backend.services.ocr import OcrService

    asked = []

    class Models:
        def ensure(self):
            asked.append(True)
            raise UserError("sin modelos", "ocr_download")

    for service in (OcrService(_Host(), None, models=Models()), ExtractService(_Host(), None, models=Models())):
        with pytest.raises(UserError):
            _ = service.processor
    assert len(asked) == 2
