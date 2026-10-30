"""Shared fixtures for the test suite.

`pyproject.toml` configures `pythonpath = ["src"]` so modules under
`src/` (e.g. `pdf_viewer.renderer`, `recent_files`) can be imported
directly without installing the project.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest


@pytest.fixture(autouse=True)
def _isolated_user_data(tmp_path_factory, monkeypatch):
    """Ningún test escribe en los datos del usuario (``~/.extraer_pdfs_*.json``):
    recientes, leyendas, perfiles de censura y configuración del asistente van a
    una carpeta temporal. Sin esto, los tests que abren PDF (p. ej. los del visor
    Qt) llenaban los recientes reales y desplazaban los del usuario."""
    from pdf_core import censorship_profiles, legends, recent_files
    from pdf_core.agent import config as agent_config

    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(recent_files, "_STORE", home / ".extraer_pdfs_recent.json")
    monkeypatch.setattr(legends, "_LEGENDS_FILE", home / ".extraer_pdfs_legends.json")
    monkeypatch.setattr(legends, "_singleton", None)
    monkeypatch.setattr(censorship_profiles, "_PROFILES_FILE", home / ".extraer_pdfs_profiles.json")
    monkeypatch.setattr(censorship_profiles, "_singleton", None)
    monkeypatch.setattr(agent_config, "_STORE", home / ".extraer_pdfs_config.json")


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A minimal 1-page PDF written to a temp file. Returns the path."""
    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 in PDF points
    page.insert_text((72, 100), "Hello from the test suite")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def sample_doc(sample_pdf: Path) -> fitz.Document:
    """Open the sample PDF as a `fitz.Document`. Closes it at teardown."""
    doc = fitz.open(str(sample_pdf))
    yield doc
    try:
        doc.close()
    except Exception:
        pass


@pytest.fixture
def multi_page_pdf(tmp_path: Path) -> Path:
    """A 3-page PDF for tests that need multiple pages."""
    path = tmp_path / "multi.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Page {i + 1}")
    doc.save(str(path))
    doc.close()
    return path
