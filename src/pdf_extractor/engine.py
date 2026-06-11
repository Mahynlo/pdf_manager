"""Extraction logic — PyMuPDF (`fitz`) + the OCR processor, never Flet.

Opens/authenticates source PDFs, runs the per-page OCR + keyword/similarity
scoring, and writes the combined output. Progress and log lines are emitted
through a `Reporter` of plain callbacks, so the engine knows nothing about the
UI driving it ([tab.py]).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import fitz

from .model import PageMatch, doc_kind_label, normalize_words, parse_pages

_PDF_PERM_COPY = 16


# ── exceptions ──────────────────────────────────────────────────────────────

class ExtractError(ValueError):
    """Base class for extraction-source errors surfaced to the UI."""


class ExtractPasswordRequiredError(ExtractError):
    """An encrypted PDF needs a password for extraction operations."""


class ExtractInvalidPasswordError(ExtractError):
    """Authentication failed for an encrypted PDF."""


class ExtractPermissionDeniedError(ExtractError):
    """The PDF does not allow content copying/extraction."""


# ── reporting ─────────────────────────────────────────────────────────────────

@dataclass
class Reporter:
    """Sink for progress/log output, wired by the tab to its Flet controls."""
    log: Callable[[str, str], None]          # (text, color)
    set_progress: Callable[[str], None]      # (text)
    log_separator: Callable[[], None]        # ()


# ── document access ───────────────────────────────────────────────────────────

def can_extract_permissions(permissions: int) -> bool:
    """Return True when permissions allow content copying (PDF_PERM_COPY = 16)."""
    if permissions < 0:
        return True
    return bool(permissions & _PDF_PERM_COPY)


def open_source_doc(path: str, password: str | None = None) -> fitz.Document:
    """Open a document for extraction, authenticating if needed.

    Raises `ExtractPasswordRequiredError` / `ExtractInvalidPasswordError` /
    `ExtractPermissionDeniedError`. The returned document is the caller's to close.
    """
    doc = fitz.open(path)
    try:
        if doc.is_encrypted:
            if not password:
                raise ExtractPasswordRequiredError("PDF protegido requiere contraseña")
            if not doc.authenticate(password):
                raise ExtractInvalidPasswordError("Contraseña incorrecta")
            if not can_extract_permissions(doc.permissions):
                raise ExtractPermissionDeniedError("El PDF no permite copia/extracción de contenido")
        return doc
    except Exception:
        doc.close()
        raise


def extract_page_text(processor, doc: fitz.Document, page_index: int) -> tuple[str, str, float, bool]:
    """Return (text, mode_label, elapsed_ms, used_ocr) for one page."""
    page = doc[page_index]
    needs_ocr = processor.page_needs_ocr(page)
    result = processor.process_page(doc, page_index, force_ocr=needs_ocr)
    text = "\n".join(seg.text for seg in result.segments if seg.text.strip())
    used_ocr = bool(result.detections)
    return text, result.mode_label, result.elapsed_ms, used_ocr


# ── scoring ─────────────────────────────────────────────────────────────────

def score_page(
    text: str,
    keywords: list[str],
    ref_tokens: set[str],
) -> tuple[bool, float, str, list[str]]:
    """Score one page. Returns (matched, score, reason, keyword_hits).

    A page matches only when it contains *all* keywords; the score is then
    boosted by the Jaccard similarity to the reference tokens.
    """
    page_text_lower = text.lower()
    kw_hits = [kw for kw in keywords if kw in page_text_lower]
    if len(kw_hits) != len(keywords):
        return False, 0.0, "", kw_hits

    score = float(len(kw_hits))
    reason = f"keywords={len(kw_hits)}"
    if ref_tokens:
        page_tokens = normalize_words(text)
        if page_tokens:
            inter = len(ref_tokens & page_tokens)
            union = len(ref_tokens | page_tokens)
            jaccard = inter / union if union else 0.0
            score += jaccard * 2
            reason += f", sim={jaccard:.2f}"
    return True, score, reason, kw_hits


# ── reference & document processing ───────────────────────────────────────────

def extract_reference_tokens(
    path: str,
    password: str | None,
    pages_input: str,
    processor,
    *,
    reporter: Reporter,
) -> set[str]:
    """Tokenize the reference document's selected pages into a token set."""
    ref_tokens: set[str] = set()
    with open_source_doc(path, password=password) as ref_doc:
        total_ref = len(ref_doc)
        selected = parse_pages(pages_input, total_ref)
        pages_to_use = sorted(selected) if selected else list(range(total_ref))
        for i in pages_to_use:
            reporter.set_progress(f"Referencia: página {i + 1}/{total_ref} — {Path(path).name}")
            text, _mode, _ms, _used_ocr = extract_page_text(processor, ref_doc, i)
            ref_tokens |= normalize_words(text)
        reporter.log(
            f"Referencia: {Path(path).name} — "
            f"{len(ref_tokens)} tokens, {len(pages_to_use)} páginas procesadas",
            "#1565C0",
        )
    return ref_tokens


def process_document(
    doc: fitz.Document,
    *,
    path: str,
    fname: str,
    file_idx: int,
    total_files: int,
    keywords: list[str],
    ref_tokens: set[str],
    hint_pages_raw: str,
    processor,
    reporter: Reporter,
) -> list[PageMatch]:
    """Scan one open document and return its matching pages (best score first)."""
    total_pages = len(doc)
    doc_kind = processor.get_doc_kind(doc)
    reporter.log(
        f"📄 [{file_idx + 1}/{total_files}] {fname} — {doc_kind_label(doc_kind)}, {total_pages} página(s)",
        "#1565C0",
    )
    if doc_kind == "scanned":
        reporter.log(
            "  ⚠ Documento escaneado — se ejecutará OCR en cada página sin texto nativo.",
            "#ED6C02",
        )

    hint_set = parse_pages(hint_pages_raw, total_pages)
    if hint_set:
        other_pages = [i for i in range(total_pages) if i not in hint_set]
        scan_order = sorted(hint_set) + other_pages
        reporter.log(
            f"  ℹ Páginas sugeridas verificadas primero: "
            f"{', '.join(str(p + 1) for p in sorted(hint_set))}",
            "onSurfaceVariant",
        )
    else:
        scan_order = list(range(total_pages))

    file_matches: list[PageMatch] = []
    pages_with_ocr = 0
    pages_skipped = 0

    for i in scan_order:
        is_hint = i in hint_set
        hint_tag = " ⭐" if is_hint else ""

        reporter.set_progress(f"Analizando: {fname} — página {i + 1}/{total_pages}{hint_tag}")

        text, mode, elapsed_ms, used_ocr = extract_page_text(processor, doc, i)
        if used_ocr:
            pages_with_ocr += 1

        time_tag = f"{elapsed_ms:.0f}ms"
        ocr_tag = " | OCR" if used_ocr else ""

        if not text.strip():
            pages_skipped += 1
            if is_hint:
                reporter.log(
                    f"  ~ Pág {i + 1}{hint_tag} [{mode} | {time_tag}]: sin texto extraíble",
                    "#ED6C02",
                )
            continue

        matched, score, reason, kw_hits = score_page(text, keywords, ref_tokens)
        if matched:
            file_matches.append(PageMatch(path, i, score, reason))
            shown = ", ".join(f'"{k}"' for k in kw_hits[:5])
            extra = f" +{len(kw_hits) - 5} más" if len(kw_hits) > 5 else ""
            reporter.log(
                f"  ✓ Pág {i + 1}{hint_tag} [{mode}{ocr_tag} | {time_tag}]: {shown}{extra}",
                "#2E7D32",
            )
        elif is_hint:
            reporter.log(
                f"  ~ Pág {i + 1}{hint_tag} [{mode}{ocr_tag} | {time_tag}]: no coincide",
                "#ED6C02",
            )

    file_matches.sort(key=lambda m: m.score, reverse=True)

    ocr_note = f", OCR en {pages_with_ocr} pág." if pages_with_ocr else ""
    skip_note = f", {pages_skipped} omitidas" if pages_skipped else ""
    if file_matches:
        reporter.log(f"  → {len(file_matches)} página(s) encontrada(s){ocr_note}{skip_note}", "#1565C0")
    else:
        reporter.log(f"  → Sin coincidencias{ocr_note}{skip_note}", "onSurfaceVariant")
    reporter.log_separator()
    return file_matches


# ── output ─────────────────────────────────────────────────────────────────

def save_matches(
    matches: list[PageMatch],
    target_paths: list[str],
    target_passwords: dict[int, str],
    dest_dir: str,
) -> Path:
    """Write the matched pages (grouped by source, deduped) to a new PDF."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / f"extraccion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    grouped: dict[str, list[PageMatch]] = {}
    for match in matches:
        grouped.setdefault(match.source_path, []).append(match)

    out_doc = fitz.open()
    try:
        for src_path, src_matches in grouped.items():
            file_idx = next(
                (idx for idx, p in enumerate(target_paths) if p == src_path), None
            )
            password = target_passwords.get(file_idx) if file_idx is not None else None
            with open_source_doc(src_path, password=password) as src_doc:
                for pidx in sorted({m.page_index for m in src_matches}):
                    out_doc.insert_pdf(src_doc, from_page=pidx, to_page=pidx)
        out_doc.save(str(out_path), garbage=4, deflate=True)
    finally:
        out_doc.close()
    return out_path
