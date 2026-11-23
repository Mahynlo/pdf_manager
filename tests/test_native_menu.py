"""El menú del botón derecho de WebView2 (``app/host.py``): solo en campos de texto o sobre texto
seleccionado, sin lo que trae de navegador. Se prueba con objetos que imitan los de WebView2."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

webview = pytest.importorskip("webview")
from app.host import _filter_menu  # noqa: E402


class Items(list):
    """Imita ``IList<CoreWebView2ContextMenuItem>``."""

    @property
    def Count(self) -> int:  # noqa: N802 (nombre de .NET)
        return len(self)

    def RemoveAt(self, index: int) -> None:  # noqa: N802
        del self[index]


def _item(name: str) -> SimpleNamespace:
    return SimpleNamespace(Name=name, Kind="Separator" if name == "-" else "Command")


def _args(names: list[str], editable: bool = False, selection: bool = False) -> SimpleNamespace:
    target = SimpleNamespace(IsEditable=editable, HasSelection=selection)
    return SimpleNamespace(ContextMenuTarget=target, MenuItems=Items(_item(n) for n in names), Handled=False)


def _names(args: SimpleNamespace) -> list[str]:
    return [item.Name for item in args.MenuItems]


def test_text_fields_keep_spelling_and_editing():
    args = _args(["spellcheck", "spellcheck", "-", "emoji", "-", "undo", "redo", "-", "cut", "copy", "paste",
                  "pasteAndMatchStyle", "selectAll", "-", "moreTools", "inspectElement"], editable=True)
    _filter_menu(args)
    assert not args.Handled
    assert _names(args) == ["spellcheck", "spellcheck", "-", "emoji", "-", "undo", "redo", "-", "cut", "copy",
                            "paste", "pasteAndMatchStyle", "selectAll"]


def test_selected_text_keeps_copy_without_browser_items():
    args = _args(["back", "forward", "reload", "-", "copy", "-", "print", "saveAs", "-", "createQrCode"], selection=True)
    _filter_menu(args)
    assert not args.Handled and _names(args) == ["copy"]


def test_elsewhere_there_is_no_menu():
    args = _args(["back", "forward", "reload", "-", "saveAs", "print"])
    _filter_menu(args)
    assert args.Handled
