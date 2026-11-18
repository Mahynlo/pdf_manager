"""Shared fixtures for the test suite.

`pyproject.toml` configures `pythonpath = ["src", "."]`, so `pdf_core` and
`app` can be imported directly without installing the project.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pdfkit import add_page, add_text

from pdf_core.pdf import Document


@pytest.fixture(autouse=True)
def _isolated_user_data(tmp_path_factory, monkeypatch):
    """Ningún test escribe en los datos del usuario (``~/.extraer_pdfs_*.json``):
    recientes, leyendas, perfiles de censura, configuración del asistente y los
    sellos propios y firmas (``~/.pdf_manager/stamps``) van a una carpeta temporal.
    Sin esto, los tests que abren PDF llenarían los recientes reales."""
    from app.backend.services import stamps
    from pdf_core import censorship_profiles, legends, recent_files
    from pdf_core.agent import config as agent_config

    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(recent_files, "_STORE", home / ".extraer_pdfs_recent.json")
    monkeypatch.setattr(legends, "_LEGENDS_FILE", home / ".extraer_pdfs_legends.json")
    monkeypatch.setattr(legends, "_singleton", None)
    monkeypatch.setattr(censorship_profiles, "_PROFILES_FILE", home / ".extraer_pdfs_profiles.json")
    monkeypatch.setattr(censorship_profiles, "_singleton", None)
    monkeypatch.setattr(agent_config, "_STORE", home / ".extraer_pdfs_config.json")
    monkeypatch.setattr(stamps, "STORE", home / "stamps")


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A minimal 1-page PDF written to a temp file. Returns the path."""
    path = tmp_path / "sample.pdf"
    with Document.new() as doc:
        add_text(add_page(doc), 72, 100, "Hello from the test suite")
        doc.save(path)
    return path
