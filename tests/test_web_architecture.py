"""Separación de capas: ``pdf_core`` no depende de ninguna interfaz y nada usa MuPDF (AGPL)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
UI_PACKAGES = {"flet", "PySide6"}
MUPDF = {"fitz", "pymupdf", "pymupdf4llm", "mupdf"}


def _imports(path: Path) -> set[str]:
    """Módulos de primer nivel importados por un archivo (también los imports diferidos)."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts and "node_modules" not in p.parts)


ALL = [*_files(ROOT / "app"), *_files(SRC / "pdf_core"), *_files(ROOT / "tests")]


def test_src_only_has_pdf_core_and_assets():
    assert {p.name for p in SRC.iterdir() if p.name != "__pycache__"} == {"pdf_core", "assets"}


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_nothing_uses_mupdf_or_an_old_interface(path):
    assert not _imports(path) & (UI_PACKAGES | MUPDF)


@pytest.mark.parametrize("path", _files(SRC / "pdf_core"), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_pdf_core_has_no_interface(path):
    assert not _imports(path) & {"app", "webview"}


@pytest.mark.parametrize("path", [*_files(ROOT / "app" / "backend"), *_files(SRC / "pdf_core")], ids=lambda p: p.relative_to(ROOT).as_posix())
def test_the_backend_does_not_know_about_the_browser(path):
    """Lo propio del navegador va en ``app/browser``: el backend es el mismo en los dos sitios."""
    assert not _imports(path) & {"js", "pyodide"}


VIEWER_SERVICES = ["viewer.py", "ocr.py", "redact.py", "ai.py"]


@pytest.mark.parametrize("name", VIEWER_SERVICES)
def test_the_viewer_reaches_its_files_through_the_host(name):
    """En el navegador los archivos del visor los tiene la ventana, no Python: el visor los lee y
    los escribe con el ``Host`` (``read_file``, ``write_file``…), nunca con rutas."""
    code = (ROOT / "app" / "backend" / "services" / name).read_text(encoding="utf-8")
    path_methods = re.findall(r"\.(read_bytes|write_bytes|read_text|write_text|stat|is_file|exists)\(", code)
    builtin_open = re.findall(r"(?<!def )(?<![\w.])open\(", code)
    assert not path_methods and not builtin_open


def test_only_the_pdf_layer_talks_to_the_engine():
    """PDFium no admite hilos: el candado de ``pdf_core.pdf`` solo protege si todo pasa por él."""
    users = {p.relative_to(ROOT).as_posix() for p in [*_files(ROOT / "app"), *_files(SRC / "pdf_core")] if "pypdfium2" in _imports(p)}
    assert users == {"src/pdf_core/pdf.py", "app/backend/services/app_service.py"}  # esta, solo para la versión


def test_mupdf_is_not_a_dependency():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert not re.search(r'^\s*"(pymupdf|flet|pyside6)', project, re.M | re.I)
    assert 'name = "pymupdf"' not in lock
