"""DocumentManagerUI — custom scrollable tab carousel with lazy suspension."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import flet as ft

if TYPE_CHECKING:
    from pdf_viewer import PDFViewerTab

_TAB_H       = 36
_TAB_W       = 180
_SCROLL_STEP = 160
# Ancho aproximado de los controles fijos de la barra (flechas + divisor + menú +
# botón "+" fijo + paddings). Se usa para decidir si las pestañas desbordan.
_RESERVED_W  = 150
_PLUS_W      = 44   # ancho del botón "+" inline (mini-pestaña)

# Chrome de la barra de pestañas: tokens de tema (se adaptan a claro/oscuro).
_TABBAR_BG   = "surfaceVariant"          # fondo de la barra
_ACTIVE_BG   = "surface"                 # pestaña activa: resalta como el contenido de abajo
_ACTIVE_TOP  = "#1565C0"                 # línea superior de acento (azul de marca)
_INACTIVE_BG = "surfaceVariant"          # pestañas inactivas: se funden con la barra
_TEXT_ACT    = "onSurface"
_TEXT_INACT  = "onSurfaceVariant"
_BORDER_CLR  = "outlineVariant"


@dataclass
class _TabEntry:
    uid: str
    label: str
    icon: str
    content: ft.Control
    closeable: bool
    close_cb: Callable | None
    viewer: "PDFViewerTab | None"
    btn: ft.Container = field(default=None, repr=False)


class DocumentManagerUI:
    """Custom scrollable tab carousel with blur/focus suspension callbacks.

    Replaces ft.Tabs. Callers use rebuild(tab_infos, selected_index) to
    synchronise the tab list; select() is handled internally via click events.
    """

    def __init__(self, page_ref: ft.Page) -> None:
        self._page    = page_ref
        self._entries: list[_TabEntry] = []
        self._active  = 0
        self._uid_seq = 0
        # Acción del botón "+" (abrir un PDF en una pestaña nueva). La fija main
        # tras definir su file-picker; si queda None el botón no hace nada.
        self.on_new_tab: Callable | None = None

        # Horizontally scrollable row of tab buttons.
        self._tabs_row = ft.Row(
            controls=[],
            scroll=ft.ScrollMode.HIDDEN,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )

        self._arr_left = ft.IconButton(
            ft.Icons.CHEVRON_LEFT,
            icon_size=20,
            tooltip="Desplazar pestañas a la izquierda",
            on_click=lambda _: self._scroll(-_SCROLL_STEP),
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4)),
        )
        self._arr_right = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT,
            icon_size=20,
            tooltip="Desplazar pestañas a la derecha",
            on_click=lambda _: self._scroll(_SCROLL_STEP),
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4)),
        )
        # Dos variantes del botón "+", se muestra una u otra según desborde:
        #  • inline: mini-pestaña pegada a la derecha de la última tab (dentro del
        #    scroll) — visible mientras las pestañas caben sin scroll.
        #  • fijo: en la barra (no scrollea) — visible cuando hay tantas pestañas
        #    que la fila hace scroll, para no tener que recorrer hasta el final.
        # Ambos abren un PDF en una pestaña nueva.
        self._new_tab_inline = ft.Container(
            content=ft.Icon(ft.Icons.ADD, size=16, color=_TEXT_INACT),
            height=_TAB_H,
            width=40,
            alignment=ft.alignment.center,
            bgcolor=_INACTIVE_BG,
            border=ft.border.only(right=ft.BorderSide(1, _BORDER_CLR)),
            tooltip="Abrir un PDF en una pestaña nueva",
            on_click=lambda _: self.on_new_tab() if self.on_new_tab else None,
            ink=True,
        )
        self._new_tab_btn = ft.IconButton(
            ft.Icons.ADD,
            icon_size=20,
            tooltip="Abrir un PDF en una pestaña nueva",
            on_click=lambda _: self.on_new_tab() if self.on_new_tab else None,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=4)),
        )
        self._overflow_btn = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            icon_size=18,
            tooltip="Lista de pestañas abiertas",
            items=[],
        )

        tab_bar = ft.Container(
            content=ft.Row(
                [
                    self._arr_left,
                    ft.Container(
                        content=self._tabs_row,
                        expand=True,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                    self._arr_right,
                    ft.Container(width=1, height=_TAB_H - 10, bgcolor=_BORDER_CLR),
                    self._overflow_btn,
                    self._new_tab_btn,
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=_TABBAR_BG,
            border=ft.border.only(bottom=ft.BorderSide(1, _BORDER_CLR)),
            height=_TAB_H + 8,
            padding=ft.padding.symmetric(vertical=4),
        )

        # Stack: all tab contents overlaid; only the active one is visible.
        self._stack = ft.Stack(controls=[], expand=True)

        self.control = ft.Column(
            controls=[tab_bar, self._stack],
            spacing=0,
            expand=True,
        )

    # ── public API ──────────────────────────────────────────────────────────

    @property
    def selected_index(self) -> int:
        return self._active

    def rebuild(self, tab_infos: list[dict], selected_index: int) -> None:
        """Synchronise the tab list.

        Uses content-identity to reuse existing entries so the Flet widget
        tree is never needlessly detached and re-attached (preserves scroll
        state, focus, etc.).
        """
        si = max(0, min(selected_index, max(0, len(tab_infos) - 1)))

        # Collect the viewer that is currently active (for blur notification).
        old_viewer: PDFViewerTab | None = None
        if self._entries and 0 <= self._active < len(self._entries):
            old_viewer = self._entries[self._active].viewer

        # Build a lookup of existing entries by content identity.
        existing: dict[int, _TabEntry] = {id(e.content): e for e in self._entries}

        new_entries: list[_TabEntry] = []
        for info in tab_infos:
            cid = id(info["content"])
            if cid in existing:
                # Reuse — update mutable fields in case they changed.
                entry = existing.pop(cid)
                entry.label    = info["label"]
                entry.close_cb = info.get("close_cb")
            else:
                # Brand-new tab.
                entry = _TabEntry(
                    uid=self._next_uid(),
                    label=info["label"],
                    icon=info["icon"],
                    content=info["content"],
                    closeable=info.get("closeable", False),
                    close_cb=info.get("close_cb"),
                    viewer=info.get("viewer"),
                )
                entry.btn = self._make_btn(entry, active=False)
                entry.content.visible = False
                self._stack.controls.append(entry.content)
            new_entries.append(entry)

        # Remove stale entries from the stack.
        for stale in existing.values():
            if stale.content in self._stack.controls:
                self._stack.controls.remove(stale.content)

        # Rebuild the tab row with the new order. El botón "+" va inline (pegado a
        # la derecha de la última pestaña) mientras las pestañas caben sin scroll;
        # cuando desbordan, se oculta el inline y se usa el "+" fijo de la barra,
        # para no tener que recorrer toda la fila hasta el final para abrir otro.
        avail = max(0.0, (self._page.width or 1280) - _RESERVED_W)
        overflowing = (len(new_entries) * _TAB_W + _PLUS_W) > avail
        self._new_tab_btn.visible    = overflowing
        self._new_tab_inline.visible = not overflowing
        tab_controls = [e.btn for e in new_entries]
        if not overflowing:
            tab_controls.append(self._new_tab_inline)
        self._tabs_row.controls = tab_controls
        self._entries = new_entries

        # Apply active/inactive styling.
        self._active = si if new_entries else 0
        for i, e in enumerate(self._entries):
            active = i == self._active
            e.content.visible = active
            self._set_btn_active(e.btn, active)

        # Blur/focus notifications based on viewer change.
        new_viewer: PDFViewerTab | None = None
        if self._entries and 0 <= self._active < len(self._entries):
            new_viewer = self._entries[self._active].viewer

        if old_viewer is not None and old_viewer is not new_viewer:
            old_viewer.on_blur()
        if new_viewer is not None and new_viewer is not old_viewer:
            new_viewer.on_focus()

        self._refresh_overflow()
        self._page.update()

        # Scroll the active tab button into view.
        # Guard: scroll_to requires the control to be mounted on the page.
        if self._entries and self._tabs_row.page is not None:
            self._tabs_row.scroll_to(key=self._entries[self._active].uid, duration=200)
            self._page.update()

    # ── internal helpers ────────────────────────────────────────────────────

    def _next_uid(self) -> str:
        self._uid_seq += 1
        return f"_dmtab_{self._uid_seq}"

    def _scroll(self, delta: float) -> None:
        self._tabs_row.scroll_to(delta=delta, duration=250)
        self._page.update()

    def _select(self, entry: _TabEntry) -> None:
        """Switch active tab to *entry*, called on button click."""
        if entry not in self._entries:
            return
        old = self._entries[self._active] if self._entries else None

        new_idx = self._entries.index(entry)
        if old and old is not entry:
            old.content.visible = False
            self._set_btn_active(old.btn, False)
            if old.viewer is not None:
                old.viewer.on_blur()

        self._active = new_idx
        entry.content.visible = True
        self._set_btn_active(entry.btn, True)
        if entry.viewer is not None:
            entry.viewer.on_focus()

        self._tabs_row.scroll_to(key=entry.uid, duration=300)
        self._page.update()

    def _make_btn(self, entry: _TabEntry, active: bool) -> ft.Container:
        close_ctrl = ft.Container(
            content=ft.Icon(ft.Icons.CLOSE, size=11, color=_TEXT_INACT),
            width=18,
            height=18,
            border_radius=9,
            tooltip="Cerrar",
            visible=entry.closeable,
            on_click=lambda _, e=entry: e.close_cb() if e.close_cb else None,
        )

        # Icon tint: red for PDF, primary for tools, default for rest.
        if entry.icon == ft.Icons.PICTURE_AS_PDF:
            icon_color = ft.Colors.RED_400
        elif entry.icon in (ft.Icons.FIND_IN_PAGE, ft.Icons.MERGE_TYPE):
            icon_color = ft.Colors.PRIMARY
        else:
            icon_color = None

        return ft.Container(
            key=entry.uid,
            content=ft.Row(
                [
                    ft.Icon(entry.icon, size=14, color=icon_color),
                    ft.Text(
                        entry.label,
                        size=12,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                        color=_TEXT_ACT if active else _TEXT_INACT,
                    ),
                    close_ctrl,
                ],
                spacing=5,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=_TAB_H,
            width=_TAB_W,
            padding=ft.padding.symmetric(horizontal=10),
            bgcolor=_ACTIVE_BG if active else _INACTIVE_BG,
            border=ft.border.only(
                top=ft.BorderSide(2, _ACTIVE_TOP if active else "transparent"),
                right=ft.BorderSide(1, _BORDER_CLR),
            ),
            on_click=lambda _, e=entry: self._select(e),
            ink=True,
            ink_color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
        )

    def _set_btn_active(self, btn: ft.Container, active: bool) -> None:
        btn.bgcolor = _ACTIVE_BG if active else _INACTIVE_BG
        btn.border = ft.border.only(
            top=ft.BorderSide(2, _ACTIVE_TOP if active else "transparent"),
            right=ft.BorderSide(1, _BORDER_CLR),
        )
        row: ft.Row = btn.content
        for ctrl in row.controls:
            if isinstance(ctrl, ft.Text):
                ctrl.color = _TEXT_ACT if active else _TEXT_INACT

    def _refresh_overflow(self) -> None:
        self._overflow_btn.items = [
            ft.PopupMenuItem(
                text=e.label,
                on_click=lambda _, e=e: self._select(e),
            )
            for e in self._entries
        ]
