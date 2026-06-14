"""Plantillas de texto ("leyendas"): menú de inserción rápida y gestor.

Permite guardar textos pre-escritos y reutilizarlos: el botón de la barra abre
un menú con las leyendas; al elegir una se activa la herramienta de texto con
ese contenido pendiente y el siguiente clic en la página abre el editor ya
relleno (el texto puede modificarse antes de colocarlo). El gestor (crear /
editar / eliminar) sigue el mismo patrón que los perfiles de censura.
"""
from __future__ import annotations

import flet as ft

from .annotations import (
    Tool, HIGHLIGHT_COLORS,
    FREETEXT_FONTS, FREETEXT_ALIGN, FREETEXT_SIZES,
    DEFAULT_TEXT_FONT, DEFAULT_TEXT_SIZE, DEFAULT_TEXT_COLOR, DEFAULT_TEXT_ALIGN,
)
from ._text_legends import get_legend_manager
from ._viewer_defs import _rgb_to_hex

_LEGEND_HDR = "#00796B"  # teal: color de acento de las leyendas
_MENU_LIMIT = 5          # nº de leyendas (más usadas) en el menú rápido


class _LegendsMixin:
    """Construye el menú de leyendas y los diálogos de gestión."""

    # ── botón de la barra de herramientas ──────────────────────────────────────

    def _make_legends_menu_btn(self) -> ft.PopupMenuButton:
        self._legends_menu = ft.PopupMenuButton(
            icon=ft.Icons.STICKY_NOTE_2_OUTLINED,
            tooltip="Leyendas (textos guardados)",
            items=[],
        )
        self._rebuild_legends_menu()
        return self._legends_menu

    def _rebuild_legends_menu(self) -> None:
        """Repuebla el menú con las leyendas MÁS USADAS (top _MENU_LIMIT); el
        resto queda accesible desde «Ver todas / Gestionar…»."""
        menu = getattr(self, "_legends_menu", None)
        if menu is None:
            return
        mgr     = get_legend_manager()
        total   = len(mgr.all())
        shown   = mgr.most_used(_MENU_LIMIT)
        items: list[ft.Control] = []
        if shown:
            for lg in shown:
                items.append(
                    ft.PopupMenuItem(
                        text=lg.name,
                        icon=ft.Icons.NOTES,
                        on_click=lambda e, lid=lg.id: self._insert_legend(lid),
                    )
                )
            items.append(ft.PopupMenuItem())  # divisor
        else:
            items.append(ft.PopupMenuItem(text="(Sin leyendas guardadas)", disabled=True))
            items.append(ft.PopupMenuItem())
        # Si hay más de las que caben en el menú, el gestor las muestra todas.
        manage_label = (
            f"Ver todas ({total}) / Gestionar…" if total > len(shown)
            else "Gestionar leyendas…"
        )
        items.append(
            ft.PopupMenuItem(
                text=manage_label,
                icon=ft.Icons.SETTINGS_OUTLINED,
                on_click=lambda e: self._open_legends_manager(),
            )
        )
        menu.items = items
        try:
            menu.update()
        except Exception:
            pass

    # ── inserción rápida ───────────────────────────────────────────────────────

    def _insert_legend(self, legend_id: str) -> None:
        """Prepara una leyenda para colocarla: activa la herramienta de texto y
        deja el contenido pendiente; el siguiente clic abre el editor relleno."""
        mgr = get_legend_manager()
        lg = mgr.get(legend_id)
        if lg is None:
            return
        # Llevar texto + estilo guardado al editor (se puede modificar al colocar).
        self._pending_legend = lg.style_props()
        # Registrar el uso para que el menú rápido priorice las más usadas.
        mgr.bump_usage(legend_id)
        self._rebuild_legends_menu()
        self._select_tool(Tool.TEXT, ft.MouseCursor.TEXT)
        self._show_snack(f"Haz clic en la página para colocar «{lg.name}»")

    # ── gestor de leyendas ─────────────────────────────────────────────────────

    def _open_legends_manager(self, e=None) -> None:
        self._legend_search_field = ft.TextField(
            hint_text="Buscar leyenda…",
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            border_radius=8,
            border_color="outlineVariant",
            focused_border_color=_LEGEND_HDR,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            on_change=lambda e: self._filter_legends(),
        )
        self._legend_list_view = ft.ListView(spacing=2, padding=ft.padding.only(top=4))
        self._rebuild_legend_list()

        self._legend_mgr_dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.STICKY_NOTE_2_OUTLINED, color=_LEGEND_HDR, size=20),
                    ft.Text("Leyendas", size=15, weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    ft.IconButton(
                        ft.Icons.ADD_CIRCLE_OUTLINE, icon_size=20,
                        tooltip="Crear nueva leyenda",
                        icon_color=_LEGEND_HDR,
                        on_click=lambda e: self._open_create_legend_dialog(),
                        style=ft.ButtonStyle(padding=ft.padding.all(4)),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
            ),
            content=ft.Container(
                ft.Column(
                    [
                        self._legend_search_field,
                        ft.Container(
                            self._legend_list_view,
                            height=300,
                            width=400,
                            border=ft.border.all(1, "outlineVariant"),
                            border_radius=8,
                        ),
                    ],
                    spacing=8,
                    tight=True,
                ),
                width=420,
                padding=ft.padding.only(top=4),
            ),
            actions=[
                ft.TextButton(
                    "Cerrar",
                    on_click=lambda e: self.page_ref.close(self._legend_mgr_dlg),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page_ref.open(self._legend_mgr_dlg)

    def _filter_legends(self) -> None:
        self._rebuild_legend_list(
            (self._legend_search_field.value or "") if self._legend_search_field else ""
        )
        try:
            self._legend_list_view.update()
        except Exception:
            pass

    def _rebuild_legend_list(self, query: str = "") -> None:
        legends = get_legend_manager().search(query)

        if not legends:
            self._legend_list_view.controls = [
                ft.Container(
                    ft.Text(
                        "No hay leyendas. Crea una con el botón ＋" if not query
                        else "Sin resultados para esa búsqueda.",
                        size=12, color="onSurfaceVariant", italic=True,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=ft.padding.all(24),
                    alignment=ft.alignment.center,
                )
            ]
            return

        tiles: list[ft.Control] = []
        for idx, lg in enumerate(legends):
            preview = lg.text.replace("\n", " ").strip()
            if len(preview) > 60:
                preview = preview[:60] + "…"
            tile = ft.Container(
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    lg.name, size=13, weight=ft.FontWeight.W_500,
                                    color="onSurface",
                                    overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                                ),
                                ft.Text(
                                    preview or "(vacía)", size=11,
                                    color="onSurfaceVariant",
                                    overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                                ),
                            ],
                            spacing=2, expand=True,
                        ),
                        ft.Row(
                            [
                                ft.IconButton(
                                    ft.Icons.PUSH_PIN_OUTLINED, icon_size=16,
                                    tooltip="Insertar en el documento",
                                    icon_color=_LEGEND_HDR,
                                    on_click=lambda e, lid=lg.id: self._insert_legend_from_manager(lid),
                                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                                ),
                                ft.IconButton(
                                    ft.Icons.EDIT_OUTLINED, icon_size=16,
                                    tooltip="Editar leyenda",
                                    icon_color="onSurfaceVariant",
                                    on_click=lambda e, lid=lg.id: self._open_create_legend_dialog(lid),
                                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                                ),
                                ft.IconButton(
                                    ft.Icons.DELETE_OUTLINE, icon_size=16,
                                    tooltip="Eliminar leyenda",
                                    icon_color="#D32F2F",
                                    on_click=lambda e, lid=lg.id, lname=lg.name: self._confirm_delete_legend(lid, lname),
                                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                                ),
                            ],
                            spacing=0,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=7),
                border_radius=6,
                bgcolor="surface" if idx % 2 == 0 else ft.Colors.with_opacity(0.05, _LEGEND_HDR),
            )
            tiles.append(tile)

        self._legend_list_view.controls = tiles

    def _insert_legend_from_manager(self, legend_id: str) -> None:
        try:
            self.page_ref.close(self._legend_mgr_dlg)
        except Exception:
            pass
        self._insert_legend(legend_id)

    # ── crear / editar leyenda ─────────────────────────────────────────────────

    def _open_create_legend_dialog(self, legend_id: str | None = None) -> None:
        try:
            self.page_ref.close(self._legend_mgr_dlg)
        except Exception:
            pass

        mgr      = get_legend_manager()
        existing = mgr.get(legend_id) if legend_id else None

        name_field = ft.TextField(
            label="Nombre de la leyenda",
            value=existing.name if existing else "",
            hint_text="Ej: Confidencial",
            dense=True,
            border_color="outlineVariant",
            focused_border_color=_LEGEND_HDR,
        )
        text_field = ft.TextField(
            label="Texto",
            value=existing.text if existing else "",
            hint_text="Texto que se insertará (se puede modificar al colocarlo)",
            multiline=True, min_lines=3, max_lines=8,
            border_color="outlineVariant",
            focused_border_color=_LEGEND_HDR,
        )

        # ── controles de estilo (misma config que el modal de texto) ───────────
        cur_font  = existing.fontname if existing else DEFAULT_TEXT_FONT
        cur_size  = int(existing.fontsize) if existing else DEFAULT_TEXT_SIZE
        cur_align = existing.align if existing else DEFAULT_TEXT_ALIGN
        cur_bw    = existing.border_width if existing else 0.0
        style = {"color": tuple(existing.color) if existing else tuple(DEFAULT_TEXT_COLOR)}

        font_dd = ft.Dropdown(
            label="Fuente", value=cur_font, width=200,
            options=[ft.dropdown.Option(key=fn, text=lbl) for lbl, fn in FREETEXT_FONTS],
        )
        size_dd = ft.Dropdown(
            label="Tamaño",
            value=str(cur_size if cur_size in FREETEXT_SIZES else DEFAULT_TEXT_SIZE),
            width=110,
            options=[ft.dropdown.Option(key=str(s), text=f"{s} pt") for s in FREETEXT_SIZES],
        )
        align_dd = ft.Dropdown(
            label="Alineación", value=str(cur_align), width=150,
            options=[ft.dropdown.Option(key=str(v), text=lbl) for lbl, v in FREETEXT_ALIGN],
        )
        swatch = ft.Container(
            width=24, height=24, border_radius=4,
            bgcolor=_rgb_to_hex(*style["color"]),
            border=ft.border.all(1, "outlineVariant"),
        )

        def _set_color(rgb):
            style["color"] = tuple(rgb)
            swatch.bgcolor = _rgb_to_hex(*rgb)
            try:
                swatch.update()
            except Exception:
                pass

        color_menu = ft.PopupMenuButton(
            content=ft.Row(
                [swatch, ft.Text("Color", size=13), ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18)],
                spacing=6, tight=True,
            ),
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        [
                            ft.Container(bgcolor=_rgb_to_hex(r, g, b), width=20, height=20, border_radius=4),
                            ft.Text(name, size=13),
                        ],
                        spacing=10,
                    ),
                    on_click=lambda e, c=rgb: _set_color(c),
                )
                for name, rgb in HIGHLIGHT_COLORS
                for r, g, b in [rgb]
            ],
        )

        def _on_border_toggle(ev):
            if border_sw.value and align_dd.value == "0":
                align_dd.value = "1"
                try:
                    align_dd.update()
                except Exception:
                    pass

        border_sw = ft.Switch(
            label="Recuadro", value=cur_bw > 0, on_change=_on_border_toggle,
        )

        def _go_back(e=None):
            try:
                self.page_ref.close(legend_edit_dlg)
            except Exception:
                pass
            self._open_legends_manager()

        def _save(e=None):
            name = (name_field.value or "").strip()
            if not name:
                name_field.error_text = "El nombre es obligatorio"
                try:
                    name_field.update()
                except Exception:
                    pass
                return
            text = text_field.value or ""
            fn = font_dd.value or DEFAULT_TEXT_FONT
            sz = int(size_dd.value or DEFAULT_TEXT_SIZE)
            al = int(align_dd.value or DEFAULT_TEXT_ALIGN)
            col = style["color"]
            bw = (cur_bw if cur_bw > 0 else 1.5) if border_sw.value else 0.0
            if legend_id:
                mgr.update(
                    legend_id, name=name, text=text,
                    fontname=fn, fontsize=sz, color=col, align=al, border_width=bw,
                )
            else:
                mgr.create(
                    name, text,
                    fontname=fn, fontsize=sz, color=col, align=al, border_width=bw,
                )
            try:
                self.page_ref.close(legend_edit_dlg)
            except Exception:
                pass
            self._rebuild_legends_menu()
            self._show_snack(f"Leyenda «{name}» guardada")
            self._open_legends_manager()

        legend_edit_dlg = ft.AlertDialog(
            title=ft.Text(
                "Editar leyenda" if existing else "Nueva leyenda",
                size=15, weight=ft.FontWeight.W_600,
            ),
            content=ft.Container(
                ft.Column(
                    [
                        name_field,
                        text_field,
                        ft.Divider(height=1, color="outlineVariant"),
                        ft.Row([font_dd, size_dd], spacing=10),
                        ft.Row([align_dd, color_menu], spacing=16,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        border_sw,
                    ],
                    spacing=12, tight=True,
                ),
                width=400,
                padding=ft.padding.only(top=4),
            ),
            actions=[
                ft.TextButton("← Volver", on_click=_go_back),
                ft.FilledButton(
                    "Guardar", icon=ft.Icons.SAVE_OUTLINED,
                    style=ft.ButtonStyle(bgcolor=_LEGEND_HDR),
                    on_click=_save,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page_ref.open(legend_edit_dlg)

    def _confirm_delete_legend(self, legend_id: str, name: str) -> None:
        def _do_delete(e):
            try:
                self.page_ref.close(confirm_dlg)
            except Exception:
                pass
            get_legend_manager().delete(legend_id)
            self._rebuild_legends_menu()
            self._show_snack(f"Leyenda «{name}» eliminada")
            self._rebuild_legend_list(
                (self._legend_search_field.value or "") if self._legend_search_field else ""
            )
            try:
                self._legend_list_view.update()
            except Exception:
                pass

        confirm_dlg = ft.AlertDialog(
            title=ft.Text("Eliminar leyenda"),
            content=ft.Text(
                f'¿Eliminar la leyenda «{name}»?\nEsta acción no se puede deshacer.',
                size=13,
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda e: self.page_ref.close(confirm_dlg),
                ),
                ft.FilledButton(
                    "Eliminar",
                    style=ft.ButtonStyle(bgcolor="#D32F2F"),
                    on_click=_do_delete,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page_ref.open(confirm_dlg)
