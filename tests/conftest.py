"""Shared fixtures for the test suite.

`pyproject.toml` configures `pythonpath = ["src"]` so modules under
`src/` (e.g. `pdf_viewer.renderer`, `recent_files`) can be imported
directly without installing the project.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest


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
