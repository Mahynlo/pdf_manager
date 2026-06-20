"""Búsqueda de texto en el documento PDF.

Implementa el panel lateral "Buscar" (modo ``"search"`` del sidebar), búsqueda
en hilo de fondo con cancelación, overlays visuales por página y navegación
entre coincidencias.  Las cajas de búsqueda se integran en el ciclo de vida
de virtualización de slots (``_search_overlays``); cuando un slot materializa
o desinfla, ``_render_mixin`` llama a ``_reapply_search_page`` /
``_clear_search_overlay_page`` respectivamente.

Interoperabilidad con censura: ``_send_to_redact`` copia el término al campo
de censura y cambia al modo "redact".
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import flet as ft
import fitz

from .renderer import BASE_SCALE

if TYPE_CHECKING:
    pass


class _SearchMixin:
    """Búsqueda de texto y panel lateral de resultados."""

    # ── panel lateral ─────────────────────────────────────────────────────────

    def _build_search_sidebar_panel(self) -> ft.Control:
        from ._viewer_defs import _OCR_PANEL_BG

        # ── campo de texto ────────────────────────────────────────────────────
        self._search_field = ft.TextField(
            hint_text="Buscar texto…",
            dense=True,
            expand=True,
            border_color="outlineVariant",
            focused_border_color="#01579B",
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            on_submit=self._on_search_submit,
            text_size=13,
        )

        # Botón Aa (distinguir mayúsculas/minúsculas)
        self._search_case_btn = ft.IconButton(
            ft.Icons.FONT_DOWNLOAD_OUTLINED,
            tooltip="Distinguir mayúsculas/minúsculas",
            icon_color="onSurfaceVariant",
            icon_size=18,
            on_click=self._toggle_search_case,
            style=ft.ButtonStyle(padding=ft.padding.all(6)),
        )

        search_row = ft.Row(
            [self._search_field, self._search_case_btn],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── navegación entre coincidencias ────────────────────────────────────
        self._search_count_label = ft.Text("", size=12, color="onSurfaceVariant",
                                           expand=True, text_align=ft.TextAlign.CENTER)

        nav_row = ft.Row(
            [
                ft.IconButton(
                    ft.Icons.ARROW_UPWARD, tooltip="Coincidencia anterior",
                    icon_size=18, on_click=self._search_prev,
                    style=ft.ButtonStyle(padding=ft.padding.all(6)),
                    icon_color="#01579B",
                ),
                self._search_count_label,
                ft.IconButton(
                    ft.Icons.ARROW_DOWNWARD, tooltip="Siguiente coincidencia",
                    icon_size=18, on_click=self._search_next,
                    style=ft.ButtonStyle(padding=ft.padding.all(6)),
                    icon_color="#01579B",
                ),
                ft.IconButton(
                    ft.Icons.CLOSE, tooltip="Limpiar búsqueda",
                    icon_size=16, on_click=self._clear_search,
                    style=ft.ButtonStyle(padding=ft.padding.all(6)),
                    icon_color="onSurfaceVariant",
                ),
                ft.IconButton(
                    ft.Icons.VISIBILITY_OFF_OUTLINED,
                    tooltip="Enviar término a Censura",
                    icon_size=16, on_click=self._send_to_redact,
                    style=ft.ButtonStyle(padding=ft.padding.all(6)),
                    icon_color="#E65100",
                ),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── lista de resultados ───────────────────────────────────────────────
        self._search_results_list = ft.ListView(
            expand=True,
            spacing=0,
            padding=ft.padding.symmetric(vertical=4),
        )

        panel = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Text(
                            "Buscar en el documento",
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color="#01579B",
                        ),
                        padding=ft.padding.only(left=12, top=12, right=12, bottom=4),
                    ),
                    ft.Container(search_row, padding=ft.padding.symmetric(horizontal=8, vertical=4)),
                    ft.Container(nav_row, padding=ft.padding.symmetric(horizontal=4, vertical=2)),
                    ft.Divider(height=1, color="outlineVariant"),
                    ft.Container(
                        content=self._search_results_list,
                        expand=True,
                        padding=ft.padding.symmetric(vertical=2),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
            bgcolor=_OCR_PANEL_BG,
        )
        return panel

    # ── búsqueda ──────────────────────────────────────────────────────────────

    def _toggle_search_case(self, e=None) -> None:
        self._search_case_sensitive = not self._search_case_sensitive
        if self._search_case_btn is not None:
            self._search_case_btn.icon_color = "#01579B" if self._search_case_sensitive else "onSurfaceVariant"
            self._search_case_btn.icon = (
                ft.Icons.FONT_DOWNLOAD if self._search_case_sensitive
                else ft.Icons.FONT_DOWNLOAD_OUTLINED
            )
            try:
                self._search_case_btn.update()
            except Exception:
                pass
        if self._search_query:
            self._on_search_submit()

    def _on_search_submit(self, e=None) -> None:
        query = (self._search_field.value or "").strip()
        if not query:
            self._clear_search()
            return

        self._search_query = query
        self._search_gen  += 1
        self._search_results.clear()
        self._search_matches_flat = []
        self._search_match_idx    = -1
        self._clear_all_search_overlays()

        self._search_count_label.value = "Buscando…"
        self._search_results_list.controls = []
        try:
            self._search_count_label.update()
            self._search_results_list.update()
        except Exception:
            pass

        gen            = self._search_gen
        case_sensitive = self._search_case_sensitive
        threading.Thread(
            target=self._search_worker,
            args=(query, case_sensitive, gen),
            daemon=True,
        ).start()

    # ── búsqueda por palabras completas ──────────────────────────────────────

    @staticmethod
    def _match_words(page, query_parts: list[str], case_sensitive: bool) -> list:
        """Devuelve lista de fitz.Quad con coincidencias de palabras completas.

        Usa el layer de texto (``get_text("words")``), que devuelve cada token
        con sus coordenadas exactas. Para frases de varias palabras busca
        tokens consecutivos en el mismo renglón. La puntuación pegada al token
        ("utilidad," → "utilidad") se ignora al comparar.
        """
        entries = page.get_text("words")   # [(x0,y0,x1,y1,word,blk,line,wi)]
        nq      = len(query_parts)
        hits    = []

        _PUNCT = ".,;:!?\"'()[]{}/-–—…«»“”‘’"

        def _norm(w: str) -> str:
            s = w.strip(_PUNCT)
            return s if case_sensitive else s.lower()

        for i in range(len(entries) - nq + 1):
            seq = entries[i : i + nq]

            # Los tokens de una frase deben estar en el mismo renglón
            if nq > 1 and not all(
                seq[j][5] == seq[0][5] and seq[j][6] == seq[0][6]
                for j in range(1, nq)
            ):
                continue

            if [_norm(e[4]) for e in seq] == query_parts:
                x0 = min(e[0] for e in seq)
                y0 = min(e[1] for e in seq)
                x1 = max(e[2] for e in seq)
                y1 = max(e[3] for e in seq)
                hits.append(fitz.Rect(x0, y0, x1, y1).quad)

        return hits

    def _search_worker(self, query: str, case_sensitive: bool, gen: int) -> None:
        """Busca *query* en todas las páginas del documento (hilo de fondo)."""
        results: dict[int, list] = {}

        with self._doc_lock:
            n = len(self.doc)

        # Normalizar la query igual que los tokens del documento
        _PUNCT = ".,;:!?\"'()[]{}/-–—…«»“”‘’"
        q_norm  = query if case_sensitive else query.lower()
        q_parts = [p.strip(_PUNCT) for p in q_norm.split() if p.strip(_PUNCT)]
        if not q_parts:
            return

        for pn in range(n):
            if self._search_gen != gen:
                return

            try:
                with self._doc_lock:
                    quads = self._match_words(self.doc[pn], q_parts, case_sensitive)
            except Exception:
                quads = []

            if quads:
                results[pn] = list(quads)
                self._render_search_overlay(pn, quads)

            # Actualización progresiva del contador (sin rebuilds costosos)
            if pn % 10 == 9 or (quads and pn < 5):
                if self._search_gen != gen:
                    return
                total = sum(len(qs) for qs in results.values())
                self._search_count_label.value = f"Buscando… ({total})"
                try:
                    self._search_count_label.update()
                except Exception:
                    pass

        if self._search_gen != gen:
            return

        # Construir lista plana ordenada por (pn, posición)
        self._search_results = results
        self._search_matches_flat = [
            (pn, qi)
            for pn, qs in sorted(results.items())
            for qi in range(len(qs))
        ]
        total = len(self._search_matches_flat)

        if total > 0:
            self._search_match_idx = 0
            self._update_search_counter()
            self._scroll_to_current_match()
            self._render_all_search_overlays()
        else:
            self._search_count_label.value = "Sin coincidencias"

        self._rebuild_results_list()

        try:
            self.page_ref.update()
        except Exception:
            pass

    # ── navegación ────────────────────────────────────────────────────────────

    def _search_next(self, e=None) -> None:
        if not self._search_matches_flat:
            return
        self._search_match_idx = (self._search_match_idx + 1) % len(self._search_matches_flat)
        self._update_search_counter()
        self._scroll_to_current_match()
        self._render_all_search_overlays()
        try:
            self.page_ref.update()
        except Exception:
            pass

    def _search_prev(self, e=None) -> None:
        if not self._search_matches_flat:
            return
        self._search_match_idx = (self._search_match_idx - 1) % len(self._search_matches_flat)
        self._update_search_counter()
        self._scroll_to_current_match()
        self._render_all_search_overlays()
        try:
            self.page_ref.update()
        except Exception:
            pass

    def _scroll_to_current_match(self) -> None:
        if self._search_match_idx < 0 or not self._search_matches_flat:
            return
        pn, qi = self._search_matches_flat[self._search_match_idx]
        if pn not in self._search_results or qi >= len(self._search_results[pn]):
            return

        quad = self._search_results[pn][qi]

        # En modo página única o doble, usar _scroll_to_page para mostrar la
        # fila correcta y actualizar current_page — el scroll continuo no aplica.
        display_mode = getattr(self, "_display_mode", "continuous")
        if display_mode in ("single", "double"):
            try:
                self._scroll_to_page(pn)
            except Exception:
                pass
            return

        # ── Modo continuo ────────────────────────────────────────────────────
        # Forzar construcción del slot si aún no estaba materializado
        try:
            self._ensure_page_built(pn)
        except Exception:
            pass

        # Coordenada de pantalla del centro del match
        scale = getattr(self, "zoom", 1.0) * BASE_SCALE
        y_mid = (quad.rect.y0 + quad.rect.y1) / 2.0 * scale

        # Posición global dentro del scroll continuo
        try:
            global_y = self._get_global_y(pn, y_mid)
            vp_h     = getattr(self, "_last_viewport_h", 600.0)
            target   = max(0.0, global_y - vp_h / 2.0)
        except Exception:
            try:
                target = self._page_cum_offsets[pn]
            except Exception:
                return

        try:
            self.viewer_scroll.scroll_to(offset=target, duration=180)
        except Exception:
            pass

    # ── overlays ──────────────────────────────────────────────────────────────

    def _render_search_overlay(self, pn: int, quads=None) -> None:
        """Dibuja cajas de búsqueda en el overlay de la página *pn*.

        Si el slot no está construido, no-op — se re-aplicará en
        ``_build_page_slot`` cuando materialice.
        """
        if pn >= len(self._search_overlays):
            return
        ov = self._search_overlays[pn]
        if ov is None:
            return

        qs    = quads if quads is not None else self._search_results.get(pn, [])
        scale = getattr(self, "zoom", 1.0) * BASE_SCALE
        cur   = (
            self._search_matches_flat[self._search_match_idx]
            if 0 <= self._search_match_idx < len(self._search_matches_flat)
            else None
        )

        boxes = []
        for qi, q in enumerate(qs):
            is_cur = (cur == (pn, qi))
            r = q.rect
            w = max(2.0, r.width  * scale)
            h = max(2.0, r.height * scale)
            boxes.append(ft.Container(
                left   = r.x0 * scale,
                top    = r.y0 * scale,
                width  = w,
                height = h,
                bgcolor = ft.Colors.with_opacity(
                    0.55 if is_cur else 0.30,
                    "#FF6F00" if is_cur else "#FDD835",
                ),
                border=ft.border.all(1.5, "#FF6F00") if is_cur else None,
                border_radius=2,
            ))

        ov.controls = boxes
        ov.visible  = bool(boxes)

    def _render_all_search_overlays(self) -> None:
        """Actualiza overlays de búsqueda en todos los slots construidos."""
        for pn in range(len(self._search_overlays)):
            if self._search_overlays[pn] is not None:
                self._render_search_overlay(pn)

    def _clear_all_search_overlays(self) -> None:
        for ov in self._search_overlays:
            if ov is not None:
                ov.controls = []
                ov.visible  = False

    def _reapply_search_page(self, pn: int) -> None:
        """Llamado desde ``_build_page_slot`` cuando un slot materializa."""
        if self._search_results.get(pn):
            self._render_search_overlay(pn)

    # ── lista de resultados ───────────────────────────────────────────────────

    def _rebuild_results_list(self) -> None:
        """Reconstruye la lista scrollable de páginas con coincidencias."""
        if self._search_results_list is None:
            return

        items: list[ft.Control] = []
        for pn in sorted(self._search_results):
            count = len(self._search_results[pn])
            # Índice del primer match de esta página en la lista plana
            first_flat = next(
                (i for i, (p, _) in enumerate(self._search_matches_flat) if p == pn),
                -1,
            )
            items.append(ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ARTICLE_OUTLINED, size=14, color="#01579B"),
                        ft.Text(
                            f"Pág. {pn + 1}",
                            size=12, weight=ft.FontWeight.W_600, color="#01579B",
                            expand=True,
                        ),
                        ft.Text(
                            f"{count}",
                            size=11, color="onSurfaceVariant",
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
                ink=True,
                border=ft.border.only(bottom=ft.BorderSide(1, "outlineVariant")),
                on_click=lambda e, fi=first_flat: self._jump_to_match(fi),
            ))

        self._search_results_list.controls = items
        try:
            self._search_results_list.update()
        except Exception:
            pass

    def _jump_to_match(self, flat_idx: int) -> None:
        if flat_idx < 0 or flat_idx >= len(self._search_matches_flat):
            return
        self._search_match_idx = flat_idx
        self._update_search_counter()
        self._scroll_to_current_match()
        self._render_all_search_overlays()
        try:
            self.page_ref.update()
        except Exception:
            pass

    # ── utilidades ────────────────────────────────────────────────────────────

    def _update_search_counter(self) -> None:
        if self._search_count_label is None:
            return
        total = len(self._search_matches_flat)
        if total == 0:
            self._search_count_label.value = "Sin coincidencias"
        else:
            idx = self._search_match_idx + 1
            self._search_count_label.value = f"{idx} de {total}"
        try:
            self._search_count_label.update()
        except Exception:
            pass

    def _clear_search(self, e=None) -> None:
        self._search_gen += 1
        self._search_results.clear()
        self._search_matches_flat = []
        self._search_match_idx    = -1
        self._search_query        = ""
        self._search_case_sensitive = False
        if self._search_field is not None:
            self._search_field.value = ""
        if self._search_count_label is not None:
            self._search_count_label.value = ""
        if self._search_results_list is not None:
            self._search_results_list.controls = []
        if self._search_case_btn is not None:
            self._search_case_btn.icon_color = "onSurfaceVariant"
            self._search_case_btn.icon       = ft.Icons.FONT_DOWNLOAD_OUTLINED
        self._clear_all_search_overlays()
        try:
            self.page_ref.update()
        except Exception:
            pass

    def _send_to_redact(self, e=None) -> None:
        """Envía el término de búsqueda actual al panel de censura."""
        term = (self._search_query or "").strip()
        if not term:
            return
        if self._redact_query_field is not None:
            self._redact_query_field.value = term
        self._switch_sidebar_mode("redact")
        self._add_redact_term()

    def _open_search(self, e=None) -> None:
        """Abre el panel de búsqueda y enfoca el campo de texto."""
        self._switch_sidebar_mode("search")
        if self._search_field is not None:
            try:
                self._search_field.focus()
            except Exception:
                pass
