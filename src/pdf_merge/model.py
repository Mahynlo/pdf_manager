"""Data model for the merge feature — no Flet, no UI concerns.

Holds the per-PDF selection state (`PDFEntry`), the immutable description of
what to merge (`MergeSource`), and the helpers that convert between a boolean
page selection and the compact 1-based range notation shown in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


# ── range helpers ─────────────────────────────────────────────────────────────

def selection_to_range(selected: list[bool]) -> str:
    """Boolean list → compact 1-based range string, e.g. '1-5, 8, 10-15'."""
    pages = [i + 1 for i, s in enumerate(selected) if s]
    if not pages:
        return ""
    ranges: list[str] = []
    start = end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = p
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(ranges)


def parse_range(text: str, total: int) -> list[bool]:
    """'1-5, 8, 10-15' (1-based, semicolons allowed) → boolean selection list."""
    selected = [False] * total
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s.strip()), int(hi_s.strip())
                lo, hi = min(lo, hi), max(lo, hi)
                for i in range(max(1, lo), min(total, hi) + 1):
                    selected[i - 1] = True
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= total:
                    selected[n - 1] = True
            except ValueError:
                pass
    return selected


# ── model ─────────────────────────────────────────────────────────────────────

class PDFEntry:
    """One source PDF added to the merge list.

    Owns the open `fitz.Document` while the entry is in the list; `close()`
    releases it when the entry is removed or the tab is closed.
    """

    def __init__(self, path: str, doc: fitz.Document, password: str | None = None):
        self.path     = path
        self.filename = Path(path).name
        self.doc      = doc
        self.password = password
        self.is_encrypted = doc.is_encrypted
        self.total    = len(self.doc)
        self.selected = [True] * self.total
        self.chips_expanded = False

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass

    @property
    def selected_pages(self) -> list[int]:
        return [i for i, s in enumerate(self.selected) if s]

    @property
    def selected_count(self) -> int:
        return sum(self.selected)

    def as_source(self) -> "MergeSource":
        """Immutable snapshot of this entry's current selection for merging."""
        return MergeSource(self.path, list(self.selected_pages), self.password)


@dataclass(frozen=True)
class MergeSource:
    """Immutable description of pages to pull from one PDF during a merge.

    Snapshots are taken before the background merge starts, so UI changes
    while merging cannot affect the result.
    """
    path: str
    pages: list[int]
    password: str | None = None
