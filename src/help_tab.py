"""Help tab — opens as a closeable tab from the navbar."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft


def _section_label(text: str) -> ft.Text:
    return ft.Text(text, size=14, weight="bold", color="primary")


def _info_row(icon: str, title: str, body: str) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Icon(icon, size=22, color="primary"),
                    bgcolor="primaryContainer",
                    padding=10,
                    border_radius=8,
                    width=44,
                    height=44,
                    alignment=ft.alignment.center,
                ),
                ft.Column(
                    [
                        ft.Text(title, size=14, weight="w600"),
                        ft.Text(body, size=12, color="onSurfaceVariant"),
                    ],
                    spacing=2,
                    expand=True,
                ),
            ],
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=10),
        border_radius=8,
    )


def _card(children: list[ft.Control]) -> ft.Container:
    return ft.Container(
        content=ft.Column(children, spacing=6),
        padding=20,
        bgcolor="surfaceVariant",
        border_radius=12,
        border=ft.border.all(1, "outlineVariant"),
    )


def _faq_row(question: str, answer: str) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                ft.Text(question, size=13, weight="w600"),
                ft.Text(answer, size=12, color="onSurfaceVariant"),
            ],
            spacing=3,
        ),
        padding=ft.padding.symmetric(horizontal=10, vertical=10),
        border_radius=8,
    )


def _build_docs_tab(page_ref: ft.Page) -> ft.Control:
    """Construye la tab de documentación con lista de MD y visor."""
    docs_dir = Path(__file__).resolve().parents[1] / "docs" / "ayuda"
    if not docs_dir.exists():
        docs_dir = Path.cwd() / "docs" / "ayuda"
    
    md_files_cache: dict[str, str] = {}
    selected_file: dict[str, str] = {"current": ""}
    
    # Cargar todos los MD disponibles
    def load_md_files() -> list[str]:
        md_files_cache.clear()
        files = []
        if docs_dir.exists():
            for f in sorted(docs_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8")
                    md_files_cache[f.name] = content
                    files.append(f.name)
                except Exception:
                    pass
        return files
    
    md_files = load_md_files()
    
    # Controles UI
    md_content = ft.Markdown(value="", selectable=True)
    doc_title = ft.Text("Selecciona un documento", size=16, weight="bold")
    doc_list = ft.Column(spacing=8, scroll="auto", expand=True)
    
    # Store button references to update styling
    button_refs: dict[str, ft.Container] = {}
    
    def update_button_styles():
        """Actualiza el estilo de los botones para resaltar el seleccionado."""
        for fname, btn in button_refs.items():
            if fname == selected_file["current"]:
                btn.bgcolor = "primary"
                btn.content.color = "onPrimary"
            else:
                btn.bgcolor = "surface"
                btn.content.color = "onSurface"
        page_ref.update()
    
    def on_doc_selected(fname: str) -> None:
        content = md_files_cache.get(fname, "")
        md_content.value = content
        doc_title.value = fname
        selected_file["current"] = fname
        update_button_styles()
    
    # Crear botones para cada documento
    if md_files:
        for fname in md_files:
            btn_text = ft.Text(fname, size=12, weight="w500")
            btn = ft.Container(
                content=btn_text,
                padding=12,
                border_radius=8,
                bgcolor="surface",
                border=ft.border.all(1, "outlineVariant"),
                on_click=lambda e, f=fname: on_doc_selected(f),
            )
            button_refs[fname] = btn
            doc_list.controls.append(btn)
        
        # Cargar el primer documento por defecto
        if md_files:
            on_doc_selected(md_files[0])
    else:
        doc_list.controls.append(
            ft.Text("📁 No hay documentos en docs/ayuda/", size=12, color="onSurfaceVariant")
        )
    
    # Panel izquierdo - Lista de documentos
    left_panel = ft.Container(
        content=ft.Column([
            ft.Text("📄 Documentos", size=14, weight="bold"),
            ft.Divider(height=1, color="outlineVariant"),
            doc_list,
        ], spacing=8),
        width=280,
        bgcolor="surfaceVariant",
        padding=16,
        border_radius=8,
    )
    
    # Panel derecho - Visor de contenido
    right_panel = ft.Container(
        content=ft.Column([
            doc_title,
            ft.Divider(height=1, color="outlineVariant"),
            ft.Container(
                content=ft.Column([md_content], scroll="auto", expand=True),
                padding=16,
                expand=True,
            ),
        ], spacing=8, expand=True),
        expand=True,
        padding=0,
    )
    
    return ft.Row([left_panel, right_panel], spacing=16, expand=True)


def _build_view(page_ref: ft.Page) -> ft.Control:
    header = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.HELP_OUTLINE, size=32, color="primary"),
                ft.Column(
                    [
                        ft.Text("Ayuda y guía de uso", size=22, weight="bold"),
                        ft.Text(
                            "Todo lo que necesitas saber para usar Extraer PDFs",
                            size=13,
                            color="onSurfaceVariant",
                        ),
                    ],
                    spacing=2,
                ),
            ],
            alignment="start",
            spacing=16,
        ),
        padding=ft.padding.only(left=20, top=20, right=20, bottom=10),
    )

    # ── Primeros pasos ───────────────────────────────────────────────────────
    getting_started = _card([
        _section_label("Primeros pasos"),
        ft.Divider(height=1, color="outlineVariant"),
        _info_row(
            ft.Icons.FOLDER_OPEN_OUTLINED,
            "Abrir un PDF",
            "Haz clic en el menú ☰ → «Abrir PDF» o presiona Ctrl+O. "
            "También puedes arrastrar un archivo PDF directamente a la ventana.",
        ),
        _info_row(
            ft.Icons.NAVIGATE_NEXT,
            "Navegar páginas",
            "Usa las flechas ↑ ↓, las teclas Re Pág / Av Pág, "
            "o el panel lateral de miniaturas.",
        ),
        _info_row(
            ft.Icons.ZOOM_IN,
            "Zoom",
            "Ctrl + rueda del ratón para zoom continuo. "
            "Ctrl+= para acercar, Ctrl+− para alejar, Ctrl+0 para zoom 100 %. "
            "Ctrl+H ajusta a la página; Ctrl+W ajusta al ancho.",
        ),
        _info_row(
            ft.Icons.SAVE_OUTLINED,
            "Guardar cambios",
            "Ctrl+S sobreescribe el archivo original. "
            "El menú de herramientas del visor incluye «Guardar PDF como…» "
            "para crear una copia en otra ubicación.",
        ),
    ])

    # ── Herramientas ─────────────────────────────────────────────────────────
    tools_card = _card([
        _section_label("Herramientas disponibles"),
        ft.Divider(height=1, color="outlineVariant"),
        _info_row(
            ft.Icons.EDIT_OUTLINED,
            "Anotaciones",
            "Resalta texto, subraya, tacha, añade notas y dibuja a mano alzada "
            "directamente sobre el PDF. Deshacer/rehacer con Ctrl+Z / Ctrl+Y.",
        ),
        _info_row(
            ft.Icons.FIND_IN_PAGE_OUTLINED,
            "Extraer texto",
            "Extrae palabras clave u OCR de uno o varios PDFs a la vez, "
            "incluso de archivos protegidos con contraseña. "
            "Abre desde el menú ☰ → «Extraer texto».",
        ),
        _info_row(
            ft.Icons.MERGE_TYPE,
            "Combinar PDFs",
            "Une múltiples PDFs en un solo documento. Reordena las páginas "
            "arrastrando las miniaturas antes de combinar. "
            "Abre desde el menú ☰ → «Combinar PDFs».",
        ),
        _info_row(
            ft.Icons.LOCK_OUTLINED,
            "Seguridad",
            "Protege un PDF con contraseña, elimina una contraseña existente "
            "o desbloquea un documento para verlo. "
            "Abre desde el menú ☰ → «Seguridad».",
        ),
        _info_row(
            ft.Icons.AUTO_AWESOME_OUTLINED,
            "Agente IA",
            "Chatea con el documento: haz preguntas, pide resúmenes o solicita "
            "análisis. Disponible dentro del visor → botón «Agente IA». "
            "Requiere una clave de API de Google Gemini u OpenAI.",
        ),
        _info_row(
            ft.Icons.SEARCH,
            "Buscar en el documento",
            "Presiona Ctrl+F dentro del visor para buscar texto. "
            "Navega entre coincidencias con las flechas ↑ ↓.",
        ),
        _info_row(
            ft.Icons.CONTENT_CUT,
            "Censurar / Redactar",
            "Selecciona regiones o texto sensible y aplica redacción permanente. "
            "El contenido censurado no se puede recuperar una vez guardado.",
        ),
    ])

    # ── Guardado y seguridad ─────────────────────────────────────────────────
    save_card = _card([
        _section_label("Guardado de cambios"),
        ft.Divider(height=1, color="outlineVariant"),
        _info_row(
            ft.Icons.SAVE,
            "Guardar en el mismo archivo (Ctrl+S)",
            "Sobreescribe el PDF original con tus anotaciones o cambios. "
            "La pestaña mostrará un punto ● cuando haya cambios sin guardar.",
        ),
        _info_row(
            ft.Icons.SAVE_AS_OUTLINED,
            "Guardar como…",
            "Crea una copia del PDF en una nueva ubicación. "
            "Úsalo cuando el PDF tiene censura aplicada para preservar el original.",
        ),
        _info_row(
            ft.Icons.WARNING_AMBER_OUTLINED,
            "Advertencia al cerrar",
            "Si intentas cerrar la app o una pestaña con cambios sin guardar, "
            "aparecerá un aviso para confirmar antes de perder los cambios.",
        ),
    ])

    # ── FAQ ──────────────────────────────────────────────────────────────────
    faq_card = _card([
        _section_label("Preguntas frecuentes"),
        ft.Divider(height=1, color="outlineVariant"),
        _faq_row(
            "¿Puedo abrir un PDF protegido con contraseña?",
            "Sí. Al abrirlo, la aplicación pedirá la contraseña automáticamente. "
            "Las operaciones que requieren permisos de propietario (editar, redactar) "
            "necesitan la contraseña de propietario, no solo la de usuario.",
        ),
        _faq_row(
            "¿Dónde se guardan las anotaciones?",
            "Las anotaciones se guardan dentro del propio archivo PDF "
            "al usar Guardar (Ctrl+S) o Guardar como. No hay archivos externos.",
        ),
        _faq_row(
            "¿La OCR funciona sin conexión a internet?",
            "Sí. La OCR usa un modelo local (OnnxTR) que se ejecuta en tu equipo. "
            "No se envían datos a ningún servidor externo.",
        ),
        _faq_row(
            "¿El agente IA requiere internet?",
            "Sí. El agente IA se conecta a Google Gemini o a la API de OpenAI. "
            "Necesitas configurar una clave de API en el panel del agente antes de usarlo.",
        ),
        _faq_row(
            "¿Puedo abrir varios PDFs a la vez?",
            "Sí. Cada PDF se abre en su propia pestaña. "
            "Usa el botón + de la barra de pestañas o Ctrl+O para abrir más.",
        ),
        _faq_row(
            "¿Cómo desinstalo la aplicación?",
            "En Windows, ve a Configuración → Aplicaciones → Extraer PDFs → Desinstalar. "
            "Los archivos de configuración quedan en tu carpeta de usuario "
            "(%USERPROFILE%\\.extraer_pdfs_config.json).",
        ),
    ])

    body = ft.Container(
        content=ft.Column(
            [getting_started, tools_card, save_card, faq_card],
            spacing=16,
            scroll="auto",
        ),
        padding=30,
        expand=True,
    )

    # Crear tabs internas: Información y Documentación
    tabs_content = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(
                text="Información",
                icon=ft.Icons.INFO_OUTLINED,
                content=ft.Column([header, ft.Divider(height=1, color="outlineVariant"), body], spacing=0),
            ),
            ft.Tab(
                text="Documentación",
                icon=ft.Icons.DESCRIPTION,
                content=_build_docs_tab(page_ref),
            ),
        ],
        expand=True,
    )

    return ft.Card(
        content=tabs_content,
        elevation=2,
        margin=10,
        expand=True,
    )


class HelpTab:
    """Closeable help tab opened from the navbar menu."""

    def __init__(self, page_ref: ft.Page, on_close: Callable[["HelpTab"], None]):
        self._page    = page_ref
        self.on_close = on_close
        self.view     = _build_view(page_ref)

    def get_tab_info(self) -> dict:
        return {
            "label":     "Ayuda",
            "icon":      ft.Icons.HELP_OUTLINE,
            "content":   self.view,
            "closeable": True,
            "close_cb":  lambda: self.on_close(self),
        }
