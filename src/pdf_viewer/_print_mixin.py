"""_PrintMixin — Impresión de PDFs.

Estrategia por plataforma
─────────────────────────
Windows
  • Listar impresoras → PowerShell  Get-Printer  (viene en Win 8+/Server 2012+)
  • Enviar trabajo    → PowerShell  Out-Printer   (Win 8+) con el PDF renderizado
    como imágenes PNG temporales inyectadas en un documento Word/XPS mínimo,
    O bien vía el comando   mspaint /pt  (fallback para XP/7).
    En la práctica la ruta más robusta y universal es generar un XPS desde
    Python y enviarlo a la cola — pero eso requiere la librería `reportlab` o
    similar.  Dado que ya usamos PyMuPDF (fitz), la ruta más simple y sin
    dependencias extra es:
      1. Renderizar cada página a PNG temporal (fitz).
      2. Llamar a  mspaint /pt <png> <printer>  para cada página  — sencillo
         pero feo (abre/cierra MS Paint).
    La alternativa recomendada y limpia es crear un PDF temporal con las
    páginas deseadas y enviarlo con:
      PowerShell  Start-Process -FilePath <pdf> -Verb PrintTo -ArgumentList <printer>
    Este verbo funciona si hay un visor PDF registrado (Adobe, Edge, Foxit…).
    Si no hay visor, fallback a imprimir página a página con mspaint.

macOS
  • Listar impresoras → lpstat -p
  • Enviar trabajo    → lp -d <printer> <pdf>   (CUPS)

Linux
  • Listar impresoras → lpstat -p  (CUPS)
  • Enviar trabajo    → lp -d <printer> <pdf>   (CUPS)

Todo sin pywin32, sin Pillow obligatorio (es opcional para el fallback de
mspaint), y compatible con `flet build`.
"""

from __future__ import annotations

import base64
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import fitz  # PyMuPDF
import flet as ft


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

_SYSTEM = platform.system()  # "Windows" | "Darwin" | "Linux"

_PRINT_THUMB_SCALE = 0.35  # A4 → ~208×295 px, suficiente para lista compacta
_PRINT_THUMB_W     = 74
_PRINT_THUMB_H     = 104


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Ejecuta un subproceso ocultando la ventana en Windows."""
    if _SYSTEM == "Windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs.setdefault("startupinfo", si)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **kwargs)


# ---------------------------------------------------------------------------
# Listado de impresoras
# ---------------------------------------------------------------------------

def _get_printers_windows() -> list[str]:
    """Usa PowerShell Get-Printer (Win 8+).  Fallback: wmic."""
    # Intento 1: PowerShell Get-Printer
    try:
        r = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-Printer | Select-Object -ExpandProperty Name",
        ])
        if r.returncode == 0:
            names = [l.strip() for l in r.stdout.splitlines() if l.strip()]
            if names:
                return names
    except FileNotFoundError:
        pass

    # Intento 2: wmic (disponible desde XP)
    try:
        r = _run(["wmic", "printer", "get", "Name", "/format:list"])
        if r.returncode == 0:
            names = []
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.lower().startswith("name="):
                    name = line.split("=", 1)[1].strip()
                    if name:
                        names.append(name)
            if names:
                return names
    except FileNotFoundError:
        pass

    return []


def _get_printers_unix() -> list[str]:
    """Usa lpstat -p (CUPS — macOS y Linux)."""
    try:
        r = _run(["lpstat", "-p"])
        if r.returncode == 0:
            names = []
            for line in r.stdout.splitlines():
                if line.startswith("printer ") or line.startswith("impresora "):
                    parts = line.split()
                    if len(parts) > 1:
                        names.append(parts[1])
            if names:
                return names
    except FileNotFoundError:
        pass
    return []


def _get_default_printer_windows() -> str:
    """Obtiene la impresora predeterminada en Windows via PowerShell."""
    try:
        r = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "(Get-WmiObject -Query 'SELECT * FROM Win32_Printer WHERE Default=$true').Name",
        ])
        if r.returncode == 0:
            name = r.stdout.strip()
            if name:
                return name
    except Exception:
        pass
    # Fallback: wmic
    try:
        r = _run(["wmic", "printer", "where", "default=TRUE", "get", "Name", "/format:list"])
        for line in r.stdout.splitlines():
            if line.lower().startswith("name="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "Impresora predeterminada"


def _get_default_printer_unix() -> str:
    try:
        r = _run(["lpstat", "-d"])
        # salida típica: "system default destination: HP_LaserJet"
        if r.returncode == 0 and ":" in r.stdout:
            return r.stdout.split(":", 1)[1].strip()
    except Exception:
        pass
    return "Impresora predeterminada"


# ---------------------------------------------------------------------------
# Envío a impresora
# ---------------------------------------------------------------------------

def _printer_is_virtual(printer: str) -> bool:
    """Detecta impresoras virtuales (PDF, XPS, OneNote…) que abren un diálogo."""
    tokens = (
        "print to pdf", "microsoft print to pdf", "adobe pdf",
        "xps document writer", "onenote", "fax",
    )
    norm = printer.lower()
    return any(t in norm for t in tokens)


def _print_windows(pdf_path: str, printer: str) -> tuple[bool, str]:
    """
    Envía pdf_path a la cola de Windows.

    Estrategia (en orden de preferencia):
    1. PowerShell Start-Process … -Verb PrintTo  (requiere visor PDF registrado)
    2. Renderizar páginas a PNG y enviar con mspaint /pt  (sin visor)

    Retorna (éxito, mensaje_error).
    """
    # ── Intento 1: PrintTo verb ──────────────────────────────────────────────
    try:
        r = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f'Start-Process -FilePath "{pdf_path}" -Verb PrintTo -ArgumentList \'"{printer}"\' -Wait',
        ], timeout=60)
        if r.returncode == 0:
            return True, ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # ── Intento 2: mspaint página a página ──────────────────────────────────
    try:
        doc = fitz.open(pdf_path)
        tmp_dir = tempfile.mkdtemp(prefix="print_pngs_")
        try:
            ok_count = 0
            for i in range(len(doc)):
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                png_path = os.path.join(tmp_dir, f"page_{i:04d}.png")
                pix.save(png_path)
                r = _run(["mspaint", "/pt", png_path, printer], timeout=30)
                if r.returncode == 0:
                    ok_count += 1
            doc.close()
            if ok_count == 0:
                return False, "mspaint no pudo enviar ninguna página."
            return True, ""
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as ex:
        return False, str(ex)


def _print_unix(pdf_path: str, printer: str, sys_plat: str) -> tuple[bool, str]:
    """Envía pdf_path a CUPS (macOS / Linux)."""
    try:
        if printer == "Impresora predeterminada" or not printer:
            cmd = ["lp", pdf_path]
        else:
            cmd = ["lp", "-d", printer, pdf_path]
        r = _run(cmd, timeout=30)
        if r.returncode == 0:
            return True, ""
        return False, r.stderr.strip() or "lp retornó error."
    except FileNotFoundError:
        # CUPS no instalado — abrir con el visor por defecto
        try:
            if sys_plat == "Darwin":
                subprocess.run(["open", "-a", "Preview", pdf_path])
            else:
                subprocess.run(["xdg-open", pdf_path])
            return True, ""
        except Exception as ex:
            return False, str(ex)
    except subprocess.TimeoutExpired:
        return False, "Tiempo de espera agotado al enviar a CUPS."


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class _PrintMixin:
    """
    Mixin de impresión cross-platform sin pywin32.

    Requiere que la clase anfitriona tenga:
        self.page_ref   : ft.Page
        self.doc        : fitz.Document
        self.current_page: int
        self.filename   : str
    Opcionales:
        self._page_images : list[ft.Image]  (para vista previa)
        self._doc_lock    : threading.Lock  (acceso thread-safe al doc)
        self._night_mode  : bool
    """

    # ── Notificaciones ────────────────────────────────────────────────────────

    def _notify_print(self, message: str, *, error: bool = False) -> None:
        if not hasattr(self, "page_ref"):
            return
        bgcolor = "#D32F2F" if error else "#2E7D32"
        self.page_ref.snack_bar = ft.SnackBar(
            ft.Text(message, color=ft.Colors.WHITE),
            open=True,
            bgcolor=bgcolor,
        )
        try:
            self.page_ref.update()
        except Exception:
            pass

    # ── API pública ───────────────────────────────────────────────────────────

    def _print_pdf(self, e=None) -> None:
        """Abre el diálogo de impresión."""
        self._build_and_show_print_dialog()

    # ── Listado de impresoras ─────────────────────────────────────────────────

    def _get_system_printers(self) -> list[str]:
        if _SYSTEM == "Windows":
            names = _get_printers_windows()
        else:
            names = _get_printers_unix()

        if not names:
            return ["Impresora predeterminada"]
        return sorted(names)

    def _resolve_selected_printer(self, printer: str) -> str:
        """Resuelve 'Impresora predeterminada' al nombre real del sistema."""
        if printer != "Impresora predeterminada":
            return printer
        if _SYSTEM == "Windows":
            return _get_default_printer_windows()
        return _get_default_printer_unix()

    # ── Thumbnails para vista previa ──────────────────────────────────────────

    def _get_print_thumb(self, pn: int) -> str | None:
        """Render page *pn* at _PRINT_THUMB_SCALE and return base64 PNG (cached)."""
        if not hasattr(self, '_print_thumb_cache'):
            self._print_thumb_cache: dict[int, str] = {}
        if pn in self._print_thumb_cache:
            return self._print_thumb_cache[pn]
        try:
            mat  = fitz.Matrix(_PRINT_THUMB_SCALE, _PRINT_THUMB_SCALE)
            lock = getattr(self, '_doc_lock', None)
            if lock:
                with lock:
                    pix = self.doc[pn].get_pixmap(matrix=mat, alpha=False)
            else:
                pix = self.doc[pn].get_pixmap(matrix=mat, alpha=False)
            b64 = base64.b64encode(pix.tobytes("png")).decode()
            del pix
            self._print_thumb_cache[pn] = b64
            return b64
        except Exception:
            return None

    def _render_print_thumbs_async(self, pages: list[int]) -> None:
        """Background-render uncached thumbnails, then refresh the preview grid."""
        cache    = getattr(self, '_print_thumb_cache', {})
        uncached = [p for p in pages if p not in cache]
        if not uncached:
            return
        cp = getattr(self, 'current_page', 0)
        uncached.sort(key=lambda p: abs(p - cp))

        def _worker() -> None:
            halfway = max(1, len(uncached) // 2)
            for i, pn in enumerate(uncached):
                self._get_print_thumb(pn)
                if i + 1 == halfway:
                    current = getattr(self, '_print_current_pages', [])
                    if current:
                        self._update_print_preview(current)
                        try:
                            self.page_ref.update()
                        except Exception:
                            pass
            current = getattr(self, '_print_current_pages', [])
            if current:
                self._update_print_preview(current)
                try:
                    self.page_ref.update()
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True, name="print-thumbs").start()

    def _compute_print_pages(self) -> list[int]:
        total = len(self.doc)
        opt   = getattr(self, '_print_range_opt', 'all')
        if opt == 'current':
            return [self.current_page]
        if opt == 'custom':
            return self._parse_page_range(getattr(self, '_print_custom_range', ''), total)
        return list(range(total))

    def _update_print_preview(self, pages: list[int]) -> None:
        """Rebuild the thumbnail list from cache only — never renders inline."""
        wrap       = getattr(self, '_print_preview_wrap', None)
        col        = getattr(self, '_print_preview_col', None)
        empty      = getattr(self, '_print_preview_empty', None)
        count_text = getattr(self, '_print_preview_count', None)
        if wrap is None or col is None:
            return

        if count_text is not None:
            count_text.value = f"{len(pages)} página(s)" if pages else ""

        if not pages:
            col.controls = [empty] if empty else []
            return

        cache = getattr(self, '_print_thumb_cache', {})
        items: list[ft.Control] = []
        for order, pn in enumerate(pages):
            b64 = cache.get(pn)
            if b64:
                thumb_img: ft.Control = ft.Image(
                    src_base64=b64,
                    width=_PRINT_THUMB_W, height=_PRINT_THUMB_H,
                    fit=ft.ImageFit.COVER,
                )
            else:
                thumb_img = ft.Container(
                    width=_PRINT_THUMB_W, height=_PRINT_THUMB_H,
                    bgcolor="#D0D0D0",
                    content=ft.Icon(ft.Icons.PICTURE_AS_PDF, size=16, color=ft.Colors.OUTLINE),
                    alignment=ft.alignment.center,
                )

            thumb_box = ft.Container(
                content=thumb_img,
                width=_PRINT_THUMB_W,
                height=_PRINT_THUMB_H,
                border=ft.border.all(1, "#BDBDBD"),
                border_radius=3,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                shadow=ft.BoxShadow(blur_radius=4, color="#18000000", offset=ft.Offset(1, 2)),
            )

            info_col = ft.Column(
                [
                    ft.Text(
                        f"Página {pn + 1}",
                        size=13, weight=ft.FontWeight.W_500, color="#1E2A38",
                    ),
                    ft.Text(
                        f"Orden: {order + 1}",
                        size=11, color="#1976D2",
                    ),
                ],
                spacing=4,
                alignment=ft.MainAxisAlignment.CENTER,
            )

            items.append(ft.Container(
                content=ft.Row(
                    [thumb_box, info_col],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=7),
                border_radius=6,
                bgcolor="#FFFFFF18" if getattr(self, "_night_mode", False) else "#FFFFFF",
                border=ft.border.all(1, "#E0E0E0"),
                tooltip=f"Página {pn + 1}",
            ))

        wrap.controls = items
        col.controls  = [wrap]

    def _refresh_print_preview(self) -> None:
        pages = self._compute_print_pages()
        self._print_current_pages = pages
        self._update_print_preview(pages)
        self._render_print_thumbs_async(pages)

    # ── Diálogo ───────────────────────────────────────────────────────────────

    def _build_and_show_print_dialog(self) -> None:
        printers    = self._get_system_printers()
        total_pages = len(self.doc)

        self._print_range_opt        = "all"
        self._print_custom_range     = ""
        self._print_selected_printer = printers[0]
        self._print_current_pages    = list(range(total_pages))

        printer_dropdown = ft.Dropdown(
            label="Destino",
            options=[ft.dropdown.Option(p) for p in printers],
            value=printers[0],
            width=280,
            on_change=lambda e: setattr(self, "_print_selected_printer", e.control.value),
        )

        range_radio = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="all",     label="Todas las páginas"),
                ft.Radio(value="current", label="Página actual"),
                ft.Radio(value="custom",  label="Rango personalizado (ej. 1-5, 8)"),
            ]),
            value="all",
            on_change=self._on_print_range_change,
        )

        self._custom_range_field = ft.TextField(
            label="Páginas a imprimir",
            hint_text="Ej: 1, 3-5",
            value="",
            disabled=True,
            width=280,
            on_change=lambda e: setattr(self, "_print_custom_range", e.control.value),
            on_blur=lambda e: self._refresh_print_preview(),
            on_submit=lambda e: self._refresh_print_preview(),
        )

        # ── panel derecho: lista vertical de miniaturas ──────────────────────
        self._print_preview_wrap  = ft.Column([], spacing=6)
        self._print_preview_empty = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.PICTURE_AS_PDF, size=36, color="#BDBDBD"),
                    ft.Text("Sin páginas", size=11, color="#999999", italic=True),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            expand=True,
            alignment=ft.alignment.center,
        )
        self._print_preview_count = ft.Text(
            f"{total_pages} página(s)", size=11, color="#666666"
        )
        self._print_preview_col = ft.Column(
            [self._print_preview_wrap],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        is_night = getattr(self, "_night_mode", False)
        right_column = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Vista previa", weight=ft.FontWeight.W_500, size=13),
                        ft.Container(expand=True),
                        self._print_preview_count,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    content=self._print_preview_col,
                    bgcolor="#2C2C2C" if is_night else "#EFEFEF",
                    border_radius=8,
                    padding=6,
                    expand=True,
                ),
            ],
            expand=True,
            spacing=8,
        )

        left_column = ft.Column(
            [
                ft.Text("Imprimir Documento", size=18, weight=ft.FontWeight.BOLD),
                printer_dropdown,
                ft.Divider(),
                ft.Text("Páginas", weight=ft.FontWeight.W_500),
                range_radio,
                self._custom_range_field,
            ],
            width=295,
            spacing=12,
        )

        dialog_content = ft.Container(
            content=ft.Row(
                [left_column, ft.VerticalDivider(width=1), right_column],
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                spacing=16,
            ),
            width=680,
            height=460,
        )

        self._print_dialog = ft.AlertDialog(
            content=dialog_content,
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self._close_print_dialog()),
                ft.ElevatedButton(
                    "Imprimir",
                    on_click=lambda e: self._execute_print(),
                    bgcolor=ft.Colors.BLUE,
                    color=ft.Colors.WHITE,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            content_padding=ft.padding.all(16),
        )

        self.page_ref.overlay.append(self._print_dialog)
        self._print_dialog.open = True
        # Muestra placeholders inmediatamente; las miniaturas cargan en background
        self._update_print_preview(self._print_current_pages)
        self.page_ref.update()
        self._render_print_thumbs_async(self._print_current_pages)

    def _on_print_range_change(self, e) -> None:
        self._print_range_opt = e.control.value
        self._custom_range_field.disabled = (self._print_range_opt != "custom")
        self._refresh_print_preview()
        self.page_ref.update()

    def _close_print_dialog(self) -> None:
        if hasattr(self, "_print_dialog"):
            self._print_dialog.open = False
            self.page_ref.update()
            if self._print_dialog in self.page_ref.overlay:
                self.page_ref.overlay.remove(self._print_dialog)
            del self._print_dialog

    # ── Ejecución de impresión ────────────────────────────────────────────────

    def _execute_print(self) -> None:
        self._close_print_dialog()

        # Determinar páginas
        total = len(self.doc)
        if self._print_range_opt == "all":
            pages_to_print = list(range(total))
        elif self._print_range_opt == "current":
            pages_to_print = [self.current_page]
        else:
            pages_to_print = self._parse_page_range(self._print_custom_range, total)

        if not pages_to_print:
            self._notify_print("Rango de páginas inválido.", error=True)
            return

        # Impresoras virtuales en Windows → guardar como PDF
        effective_printer = self._resolve_selected_printer(self._print_selected_printer)
        if _SYSTEM == "Windows" and _printer_is_virtual(effective_printer):
            self._save_pdf_subset(pages_to_print)
            return

        self._notify_print("Preparando documento para imprimir…")

        # Extraer páginas en el hilo principal (fitz no es thread-safe)
        temp_path = self._build_temp_pdf(pages_to_print)
        if temp_path is None:
            return  # error ya notificado

        threading.Thread(
            target=self._print_worker,
            args=(temp_path, effective_printer),
            daemon=True,
            name="print-worker",
        ).start()

    def _build_temp_pdf(self, pages: list[int]) -> str | None:
        """Crea un PDF temporal con las páginas indicadas. Retorna la ruta o None."""
        try:
            tmp_pdf = fitz.open()
            lock = getattr(self, "_doc_lock", None)
            if lock:
                with lock:
                    for p in pages:
                        tmp_pdf.insert_pdf(self.doc, from_page=p, to_page=p)
            else:
                for p in pages:
                    tmp_pdf.insert_pdf(self.doc, from_page=p, to_page=p)

            fd, path = tempfile.mkstemp(suffix=".pdf", prefix="impresion_")
            os.close(fd)
            tmp_pdf.save(path)
            tmp_pdf.close()
            return path
        except Exception as ex:
            print(f"Error creando PDF temporal: {ex}")
            self._notify_print("Error preparando el documento.", error=True)
            return None

    def _print_worker(self, temp_path: str, printer: str) -> None:
        """Hilo de impresión: envía el PDF al sistema operativo."""
        try:
            if _SYSTEM == "Windows":
                ok, err = _print_windows(temp_path, printer)
            else:
                ok, err = _print_unix(temp_path, printer, _SYSTEM)

            if ok:
                self._notify_print(f"Documento enviado a: {printer}")
            else:
                self._notify_print(f"Error al imprimir: {err}", error=True)
        except Exception as ex:
            self._notify_print(f"Error inesperado: {ex}", error=True)
        finally:
            self._schedule_temp_file_deletion(temp_path)

    # ── Guardar subconjunto de páginas (impresoras virtuales) ─────────────────

    def _save_pdf_subset(self, pages: list[int]) -> None:
        """Abre el file picker para guardar las páginas seleccionadas como PDF."""
        self._ensure_print_save_picker()
        self._pending_print_pages = pages
        suggested = f"{Path(self.filename).stem}_impreso.pdf"
        self._notify_print("Selecciona dónde guardar el PDF…")
        self._print_save_picker.save_file(
            dialog_title="Guardar PDF",
            file_name=suggested,
            allowed_extensions=["pdf"],
        )

    def _ensure_print_save_picker(self) -> None:
        if not hasattr(self, "_print_save_picker"):
            self._print_save_picker = ft.FilePicker(on_result=self._on_print_save_result)
        if self._print_save_picker not in self.page_ref.overlay:
            self.page_ref.overlay.append(self._print_save_picker)
            self.page_ref.update()

    def _on_print_save_result(self, e: ft.FilePickerResultEvent) -> None:
        pages = getattr(self, "_pending_print_pages", None)
        self._pending_print_pages = None

        if not e.path or pages is None:
            self._notify_print("Guardado cancelado.")
            return

        temp_path = self._build_temp_pdf(pages)
        if temp_path is None:
            return

        try:
            shutil.copyfile(temp_path, e.path)
            self._notify_print(f"PDF guardado: {Path(e.path).name}")
        except Exception as ex:
            self._notify_print(f"No se pudo guardar: {ex}", error=True)
        finally:
            self._schedule_temp_file_deletion(temp_path, delay_seconds=0)

    # ── Utilidades ────────────────────────────────────────────────────────────

    def _schedule_temp_file_deletion(self, path: str, delay_seconds: float = 120.0) -> None:
        def _delete():
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as ex:
                print(f"No se pudo eliminar temporal {path}: {ex}")

        t = threading.Timer(delay_seconds, _delete)
        t.daemon = True
        t.start()

    def _parse_page_range(self, range_str: str, total_pages: int) -> list[int]:
        pages: set[int] = set()
        for part in (p.strip() for p in range_str.split(",") if p.strip()):
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    start = max(0, int(a) - 1)
                    end   = min(total_pages - 1, int(b) - 1)
                    if start <= end:
                        pages.update(range(start, end + 1))
                except ValueError:
                    continue
            else:
                try:
                    idx = int(part) - 1
                    if 0 <= idx < total_pages:
                        pages.add(idx)
                except ValueError:
                    continue
        return sorted(pages)