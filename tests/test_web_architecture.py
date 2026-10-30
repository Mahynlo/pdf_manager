"""Separación de la versión web: ``app/`` solo usa ``pdf_core`` de ``src/``, y ``pdf_core`` no
depende de ninguna interfaz. Así Qt (y después Flet) se pueden retirar sin tocar la app."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
UI_PACKAGES = {"flet", "PySide6", "src_qt"}
# Todo lo que hay en src/ salvo pdf_core es de la versión Flet (o compatibilidad para ella).
LEGACY = {p.stem for p in SRC.iterdir() if (p.suffix == ".py" or (p / "__init__.py").exists())} - {"pdf_core"}


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
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def test_legacy_modules_are_detected():
    assert {"pdf_viewer", "pdf_merge", "recent_files", "main"} <= LEGACY


@pytest.mark.parametrize("path", _files(ROOT / "app"), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_app_only_uses_pdf_core_from_src(path):
    assert not _imports(path) & (LEGACY | UI_PACKAGES)


@pytest.mark.parametrize("path", _files(SRC / "pdf_core"), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_pdf_core_has_no_interface(path):
    assert not _imports(path) & (LEGACY | UI_PACKAGES | {"app", "webview"})


def test_old_paths_are_the_same_modules():
    """Los módulos de compatibilidad no duplican estado: son el mismo objeto."""
    import page_ranges
    import pdf_extractor.engine
    import pdf_merge.model
    import pdf_security
    import pdf_viewer._text_legends
    import pdf_viewer.ocr
    import recent_files

    from pdf_core import legends, ocr
    from pdf_core import page_ranges as core_ranges
    from pdf_core import recent_files as core_recent
    from pdf_core.extractor import engine as extractor_engine
    from pdf_core.merge import model as merge_model
    from pdf_core.security import PDFSecurityManager

    assert recent_files is core_recent
    assert page_ranges is core_ranges
    assert pdf_extractor.engine is extractor_engine
    assert pdf_merge.model is merge_model
    assert pdf_viewer._text_legends is legends
    assert pdf_viewer.ocr.processor is ocr.processor
    assert pdf_viewer.ocr.OCRProcessor is ocr.OCRProcessor
    assert pdf_security.PDFSecurityManager is PDFSecurityManager
