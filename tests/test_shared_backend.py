"""Módulos sin interfaz de ``pdf_core``: rangos, texto, palabras clave y Unir."""

from __future__ import annotations

from pathlib import Path

import pytest
from pdfkit import pdf_bytes, run_engine

from pdf_core.extractor.engine import MatchOptions, score_page
from pdf_core.extractor.model import collect_keywords
from pdf_core.merge.engine import MergeOptions, merge_pages
from pdf_core.merge.model import MergePage, parse_range
from pdf_core.page_ranges import parse_page_list, parse_pages
from pdf_core.pdf import Document
from pdf_core.text_utils import fold_accents


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
    path.write_bytes(pdf_bytes([[(72, 72, f"{path.stem}-{i + 1}")] for i in range(pages)]))
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
    with Document.open(out) as doc:
        assert total == len(doc) == 4                   # a(1) + blanca + b(2)
        assert doc[0].rotation == 90
        assert doc[1].text().strip() == ""              # hoja en blanco
        assert doc[2].text().strip() == "b-2"           # orden intercalado respetado
        assert doc.toc() == []


def test_merge_pages_bookmarks(tmp_path):
    a = _pdf(tmp_path / "a.pdf", 2)
    b = _pdf(tmp_path / "b.pdf", 1)
    out = tmp_path / "out.pdf"
    merge_pages(
        [MergePage(a, 0), MergePage(a, 1), MergePage(b, 0)], str(out), options=MergeOptions(bookmarks=True),
        outline=lambda data, items: run_engine("outline", data, {"items": items}),
    )
    with Document.open(out) as doc:
        assert doc.toc() == [(1, "a", 0), (1, "b", 2)]
