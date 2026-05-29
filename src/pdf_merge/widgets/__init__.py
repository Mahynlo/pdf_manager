"""UI components for the merge tab.

Each class builds and owns a focused part of the Flet widget tree; `tab.py`
assembles them and holds the shared state.
"""
from .entry_card import EntryCard
from .lightbox import LightboxDialog
from .password_dialog import PasswordDialog
from .pdf_list import PdfListPanel
from .preview_grid import PreviewGrid

__all__ = [
    "EntryCard",
    "LightboxDialog",
    "PasswordDialog",
    "PdfListPanel",
    "PreviewGrid",
]
