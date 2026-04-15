# home.py - HomePage clase que maneja la pantalla de inicio archivos recientes y tarjetas de acción.
#======[imports]================================================================
from __future__ import annotations 

from pathlib import Path 
from typing import Callable 

import flet as ft 
import recent_files as rf 

# ========[Dimensions]==============================================================
_RECENT_W      = 280  
_CARD_W        = 220
_CARD_H        = 195

# ========[Helper Functions]========================================================
def _row_hover(e: ft.HoverEvent) -> None:
    # SECONDARY_CONTAINER es nativo y seguro para estados de hover sutiles en M3
    e.control.bgcolor = ft.Colors.SECONDARY_CONTAINER if e.data == "true" else None
    e.control.update()

# ========[Main Class Home page]==============================================================
class HomePage:
    """Manages the static home tab: recent files, action cards and settings."""

    def __init__(
        self,
        page_ref: ft.Page,
        on_open_extractor: Callable[[], None],
        on_open_merge: Callable[[], None],
        on_open_picker: Callable[[], None],
        on_open_pdf: Callable[[str], None],
    ):
        self._page              = page_ref
        self._on_open_extractor = on_open_extractor
        self._on_open_merge     = on_open_merge
        self._on_open_picker    = on_open_picker
        self._on_open_pdf       = on_open_pdf

        self._recent_list: ft.ListView | None = None
        self._tab: ft.Tab | None = None

        self._build()

    # =======[Public API]================================================================
    def refresh_recent(self) -> None:
        """Reload the recent-files list from disk and update the UI."""
        if self._recent_list is None:
            return
        self._recent_list.controls = self._make_recent_rows()
        try:
            self._recent_list.update()
        except Exception:
            pass

    def get_tab(self) -> ft.Tab:
        if self._tab is None:
            self._tab = ft.Tab(
                tab_content=ft.Row(
                    [
                        ft.Icon(ft.Icons.HOME_OUTLINED, size=18),
                        ft.Text("Inicio", size=14, weight=ft.FontWeight.W_500),
                    ],
                    spacing=8,
                    tight=True,
                ),
                content=self.view,
            )
        return self._tab

    # ========[Recent Files Panel]========================================================
    def _make_recent_rows(self) -> list[ft.Control]:
        files = rf.load()
        if not files:
            return [
                ft.Container(
                    ft.Text(
                        "Sin archivos recientes",
                        size=13,
                        color=ft.Colors.OUTLINE,
                        italic=True,
                    ),
                    padding=ft.padding.symmetric(horizontal=12, vertical=20),
                    alignment=ft.alignment.center,
                )
            ]

        rows: list[ft.Control] = []
        for path in files:
            p     = Path(path)
            _path = path  # capture for lambda

            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.PICTURE_AS_PDF,
                                color=ft.Colors.ERROR,
                                size=22
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        p.name,
                                        size=13,
                                        weight=ft.FontWeight.W_500,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                        color=ft.Colors.ON_SURFACE,
                                    ),
                                    ft.Text(
                                        str(p.parent),
                                        size=11,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                ft.Icons.OPEN_IN_NEW,
                                icon_size=16,
                                tooltip="Abrir",
                                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                                on_click=lambda e, p=_path: self._on_open_pdf(p),
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(horizontal=10, vertical=8),
                    border_radius=8,
                    on_hover=_row_hover,
                    on_click=lambda e, p=_path: self._on_open_pdf(p),
                )
            )
        return rows

    # ========[Build]===================================================================
    def _build(self) -> None:

        # ========[Recent Files Panel]========================================================
        self._recent_list = ft.ListView(
            controls=self._make_recent_rows(),
            spacing=4,
            expand=True,
        )

        recent_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.HISTORY, size=20, color=ft.Colors.PRIMARY),
                            ft.Text(
                                "Archivos recientes",
                                size=15,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.ON_SURFACE,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color=ft.Colors.OUTLINE),
                    ft.Container(self._recent_list, expand=True),
                ],
                spacing=12,
                expand=True,
            ),
            width=_RECENT_W,
            padding=ft.padding.all(20),
            # Cambiado a SURFACE puro (BACKGROUND fue removido de la API de Flet 0.28)
            bgcolor=ft.Colors.SURFACE, 
            border=ft.border.only(right=ft.BorderSide(1, ft.Colors.OUTLINE)),
        )

        # ========[Action Cards]============================================================
        def _card(
            icon: str,
            container_color: str,
            on_container_color: str,
            title: str,
            subtitle: str,
            on_click: Callable,
        ) -> ft.Container:
            
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.Icon(icon, size=36, color=on_container_color),
                            bgcolor=container_color,
                            border_radius=12,
                            padding=ft.padding.all(16),
                        ),
                        ft.Text(
                            title,
                            size=15,
                            weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.CENTER,
                            color=ft.Colors.ON_SURFACE,
                        ),
                        ft.Text(
                            subtitle,
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                ),
                width=_CARD_W,
                height=_CARD_H,
                padding=ft.padding.all(20),
                bgcolor=ft.Colors.SURFACE,
                border_radius=16,
                border=ft.border.all(1, ft.Colors.OUTLINE),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=10,
                    color=ft.Colors.SHADOW,
                    offset=ft.Offset(0, 2),
                ),
                on_click=on_click,
                ink=True,
            )

        cards_row = ft.Row(
            [
                _card(
                    icon=ft.Icons.FIND_IN_PAGE,
                    container_color=ft.Colors.PRIMARY_CONTAINER,
                    on_container_color=ft.Colors.ON_PRIMARY_CONTAINER,
                    title="Extraer texto de PDF",
                    subtitle="Busca y extrae páginas\npor palabras clave",
                    on_click=lambda e: self._on_open_extractor(),
                ),
                _card(
                    icon=ft.Icons.MERGE_TYPE,
                    container_color=ft.Colors.SECONDARY_CONTAINER,
                    on_container_color=ft.Colors.ON_SECONDARY_CONTAINER,
                    title="Combinar PDFs",
                    subtitle="Une varios PDFs\neligiendo las páginas",
                    on_click=lambda e: self._on_open_merge(),
                ),
                _card(
                    icon=ft.Icons.DOCUMENT_SCANNER,
                    container_color=ft.Colors.TERTIARY_CONTAINER,
                    on_container_color=ft.Colors.ON_TERTIARY_CONTAINER,
                    title="OCR de PDF",
                    subtitle="Abre un PDF y ejecuta\nreconocimiento de texto",
                    on_click=lambda e: self._on_open_picker(),
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=24,
            wrap=True,
        )

        center_panel = ft.Column(
            [
                ft.Text(
                    "¿Qué quieres hacer?",
                    size=26,
                    weight=ft.FontWeight.W_800,
                    color=ft.Colors.ON_SURFACE,
                ),
                ft.Text(
                    "Selecciona una opción para comenzar",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Container(height=24), 
                cards_row,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            expand=True,
        )

        # ========[Assemble]================================================================
        main_row = ft.Row(
            [recent_panel, center_panel],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        self.view = ft.Column(
            [main_row],
            spacing=0,
            expand=True,
        )