# home.py - HomePage clase que maneja la pantalla de inicio archivos recientes y tarjetas de acción.
#======[imports]================================================================
from __future__ import annotations 

from pathlib import Path 
from typing import Callable 

import flet as ft 
import recent_files as rf 

# ========[Dimensions window]==============================================================
_RECENT_W = 280  
_CARD_W = 220
_CARD_H = 195

# ========[Helper Functions]========================================================
def _row_hover(e: ft.HoverEvent) -> None:
    # Usamos un color hexadecimal en lugar de ft.Colors para evitar errores
    e.control.bgcolor = "#F0F4F8" if e.data == "true" else None
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
        on_open_security: Callable[[], None],
        on_open_pdf: Callable[[str], None],
    ):
        self._page              = page_ref 
        self._on_open_extractor = on_open_extractor 
        self._on_open_merge     = on_open_merge 
        self._on_open_picker    = on_open_picker 
        self._on_open_security  = on_open_security
        self._on_open_pdf       = on_open_pdf 

        self._recent_list: ft.ListView | None = None 
        self._tab: ft.Tab | None = None 

        self._build() 

    # ========[Public API]================================================================
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
                        ft.Icon(ft.Icons.HOME_OUTLINED, size=18, color="#1565C0"),
                        ft.Text("Inicio", size=14, weight="w500"),
                    ],
                    spacing=8,
                    tight=True,
                ),
                content=self.view,
            )
        return self._tab

    def get_tab_info(self) -> dict:
        return {
            "label": "Inicio",
            "icon": ft.Icons.HOME_OUTLINED,
            "content": self.view,
            "closeable": False,
        }

    # ========[Recent Files Panel]========================================================
    def _make_recent_rows(self) -> list[ft.Control]:
        files = rf.load()
        if not files:
            return [
                ft.Container(
                    ft.Text(
                        "Sin archivos recientes",
                        size=13,
                        color="#999999",
                        italic=True,
                    ),
                    padding=ft.padding.symmetric(horizontal=12, vertical=20),
                    alignment=ft.alignment.center,
                )
            ]

        rows: list[ft.Control] = []
        for path in files:
            p     = Path(path)
            _path = path  

            rows.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.PICTURE_AS_PDF,
                                color="#D32F2F",
                                size=22
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        p.name,
                                        size=13,
                                        weight="w500",
                                        max_lines=1,
                                        overflow="ellipsis",
                                        color="#1E2A38",
                                    ),
                                    ft.Text(
                                        str(p.parent),
                                        size=11,
                                        color="#666666",
                                        max_lines=1,
                                        overflow="ellipsis",
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                ft.Icons.OPEN_IN_NEW,
                                icon_size=16,
                                tooltip="Abrir",
                                icon_color="#666666",
                                on_click=lambda e, p=_path: self._on_open_pdf(p),
                            ),
                        ],
                        spacing=12,
                        vertical_alignment="center",
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
                            ft.Icon(ft.Icons.HISTORY, size=20, color="#1565C0"),
                            ft.Text(
                                "Archivos recientes",
                                size=15,
                                weight="bold",
                                color="#1E2A38",
                            ),
                        ],
                        spacing=8,
                        vertical_alignment="center",
                    ),
                    ft.Divider(height=1, color="#E0E0E0"),
                    ft.Container(self._recent_list, expand=True),
                ],
                spacing=12,
                expand=True,
            ),
            width=_RECENT_W,
            padding=ft.padding.all(20),
            bgcolor="#FAFAFA", 
            border=ft.border.only(right=ft.BorderSide(1, "#E0E0E0")),
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
                            padding=16,
                        ),
                        ft.Text(
                            title,
                            size=15,
                            weight="bold",
                            text_align="center",
                            color="#1E2A38",
                        ),
                        ft.Text(
                            subtitle,
                            size=12,
                            color="#666666",
                            text_align="center",
                        ),
                    ],
                    alignment="center",
                    horizontal_alignment="center",
                    spacing=12,
                ),
                width=_CARD_W,
                height=_CARD_H,
                padding=20,
                bgcolor="#FFFFFF",
                border_radius=16,
                border=ft.border.all(1, "#E0E0E0"),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=10,
                    color="#1A000000",  # Sombra negra muy transparente (10% opacidad)
                    offset=ft.Offset(0, 4),
                ),
                on_click=on_click,
                ink=True,
            )

        cards_row = ft.Row(
            [
                _card(
                    icon=ft.Icons.FIND_IN_PAGE,
                    container_color="#E3F2FD",  # Azul muy claro
                    on_container_color="#1565C0", # Azul fuerte
                    title="Extraer texto de PDF",
                    subtitle="Busca y extrae páginas\npor palabras clave",
                    on_click=lambda e: self._on_open_extractor(),
                ),
                _card(
                    icon=ft.Icons.MERGE_TYPE,
                    container_color="#E8F5E9",  # Verde muy claro
                    on_container_color="#2E7D32", # Verde fuerte
                    title="Combinar PDFs",
                    subtitle="Une varios PDFs\neligiendo las páginas",
                    on_click=lambda e: self._on_open_merge(),
                ),
                _card(
                    icon=ft.Icons.DOCUMENT_SCANNER,
                    container_color="#FFF3E0",  # Naranja muy claro
                    on_container_color="#E65100", # Naranja fuerte
                    title="OCR de PDF",
                    subtitle="Abre un PDF y ejecuta\nreconocimiento de texto",
                    on_click=lambda e: self._on_open_picker(),
                ),
                _card(
                    icon=ft.Icons.SECURITY,
                    container_color="#FFF8E1",  # Amarillo muy claro
                    on_container_color="#F9A825", # Naranja/Dorado fuerte
                    title="Gestión de Seguridad",
                    subtitle="Desbloquea y protege\ntus documentos",
                    on_click=lambda e: self._on_open_security(),
                ),
            ],
            alignment="center",
            spacing=24,
            wrap=True,
        )

        center_panel = ft.Column(
            [
                ft.Icon(ft.Icons.GRID_VIEW, size=48, color="#E0E0E0"),
                ft.Text(
                    "¿Qué quieres hacer hoy?",
                    size=26,
                    weight="w800",
                    color="#1E2A38",
                ),
                ft.Text(
                    "Selecciona una herramienta para comenzar a trabajar",
                    size=14,
                    color="#666666",
                ),
                ft.Container(height=32), 
                cards_row,
            ],
            alignment="center",
            horizontal_alignment="center",
            spacing=4,
            expand=True,
        )

        # ========[Assemble]================================================================
        main_row = ft.Row(
            [recent_panel, center_panel],
            expand=True,
            spacing=0,
            vertical_alignment="stretch",
        )

        self.view = ft.Container(
            content=main_row,
            bgcolor="#FFFFFF",
            expand=True,
        )