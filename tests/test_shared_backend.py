"""Módulos sin interfaz compartidos por las versiones Flet y PySide6."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import fitz
import pytest
from page_ranges import parse_page_list, parse_pages
from pdf_extractor.engine import MatchOptions, score_page
from pdf_extractor.model import collect_keywords
from pdf_merge.engine import MergeOptions, merge_pages
from pdf_merge.model import MergePage, parse_range
from text_utils import fold_accents

ROOT = Path(__file__).resolve().parents[1]


# ── page_ranges ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text, expected",
    [
        ("1-3, 5", [0, 1, 2, 4]),
        ("5-3", [2, 3, 4]),          # rango invertido
        ("2; 4", [1, 3]),             # ; como separador
        ("0, -1, abc, 99", []),       # fuera de rango o inválido
        ("", []),
    ],
)
def test_parse_page_list(text, expected):
    assert parse_page_list(text, 10) == expected


def test_merge_parse_range_uses_shared_parser():
    assert parse_range("1, 3", 4) == [True, False, True, False]
    assert {i for i, sel in enumerate(parse_range("2-3", 4)) if sel} == parse_pages("2-3", 4)


# ── text_utils ───────────────────────────────────────────────────────────────
def test_fold_accents_keeps_enye_and_length():
    assert fold_accents("Comité Pública") == "Comite Publica"
    assert fold_accents("año") == "año"
    assert len(fold_accents("ÁÉÍÓÚ")) == 5


# ── extractor engine ─────────────────────────────────────────────────────────
def test_default_match_options_keep_original_behaviour():
    matched, *_ = score_page("Informe de Pagos", collect_keywords("informe, pagos"), set())
    assert matched


def test_case_sensitive_keywords_are_not_lowercased():
    keywords = collect_keywords("ONU", lower=False)
    opts = MatchOptions(case_sensitive=True)
    assert score_page("Reunión de la ONU", keywords, set(), opts)[0]
    assert not score_page("reunión de la onu", keywords, set(), opts)[0]


def test_match_options_any_accents_whole_word():
    assert score_page("pago", ["pago", "nómina"], set(), MatchOptions(match_all=False))[0]
    assert score_page("NOMINA", ["nómina"], set(), MatchOptions(ignore_accents=True))[0]
    assert not score_page("pagos", ["pago"], set(), MatchOptions(whole_word=True))[0]


# ── merge engine ─────────────────────────────────────────────────────────────
def _pdf(path: Path, pages: int) -> str:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{path.stem}-{i + 1}")
    doc.save(str(path))
    doc.close()
    return str(path)


def test_merge_pages_interleaves_rotates_and_pads_duplex(tmp_path):
    a = _pdf(tmp_path / "a.pdf", 1)
    b = _pdf(tmp_path / "b.pdf", 2)
    out = tmp_path / "out.pdf"
    # Dúplex sin marcadores (antes el dúplex solo funcionaba con marcadores).
    total = merge_pages(
        [MergePage(a, 0, rotation=90), MergePage(b, 1), MergePage(b, 0)],
        str(out),
        options=MergeOptions(duplex=True),
    )
    with fitz.open(str(out)) as doc:
        assert total == len(doc) == 4                   # a(1) + blanca + b(2)
        assert doc[0].rotation == 90
        assert doc[1].get_text().strip() == ""          # hoja en blanco
        assert doc[2].get_text().strip() == "b-2"       # orden intercalado respetado
        assert doc.get_toc() == []


def test_merge_pages_bookmarks(tmp_path):
    a = _pdf(tmp_path / "a.pdf", 2)
    b = _pdf(tmp_path / "b.pdf", 1)
    out = tmp_path / "out.pdf"
    merge_pages([MergePage(a, 0), MergePage(a, 1), MergePage(b, 0)], str(out), options=MergeOptions(bookmarks=True))
    with fitz.open(str(out)) as doc:
        assert doc.get_toc() == [[1, "a", 1], [1, "b", 3]]


# ── separación Flet / Qt ─────────────────────────────────────────────────────
@pytest.mark.skipif(not (ROOT / "src_qt").is_dir(), reason="la versión Qt no está (no se sube al repositorio)")
def test_qt_client_does_not_import_flet():
    code = (
        "import sys; sys.path[:0] = ['.', 'src'];"
        "import src_qt.ui.shell.main_window;"
        "print('flet' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={"QT_QPA_PLATFORM": "offscreen", **__import__("os").environ})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
