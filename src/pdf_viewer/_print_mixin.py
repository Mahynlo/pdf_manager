import tempfile
import os
import shutil
import subprocess
import platform
import threading
import importlib
from pathlib import Path
import flet as ft
import fitz

class _PrintMixin:
    def _notify_print(self, message: str, *, error: bool = False) -> None:
        if not hasattr(self, 'page_ref'):
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

    def _print_pdf(self, e=None) -> None:
        """Opens the print dialog."""
        self._build_and_show_print_dialog()

    def _get_system_printers(self) -> list[str]:
        printers = []
        sys_plat = platform.system()
        try:
            if sys_plat == "Windows":
                win32print = importlib.import_module("win32print")
                # EnumPrinters will return a tuple of tuples.
                # Format: (flags, description, name, comment)
                printer_info = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
                for p in printer_info:
                    printers.append(p[2])
            else:
                # Linux/macOS
                result = subprocess.run(['lpstat', '-p'], capture_output=True, text=True)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('printer '):
                            parts = line.split(' ')
                            if len(parts) > 1:
                                printers.append(parts[1])
        except Exception as ex:
            print(f"Error fetching printers: {ex}")
        
        if not printers:
            printers = ["Impresora predeterminada"]
        else:
            printers = sorted(printers)
        return printers

    def _printer_requires_interaction(self, printer: str) -> bool:
        normalized = printer.lower()
        return any(
            token in normalized
            for token in (
                "print to pdf",
                "microsoft print to pdf",
                "adobe pdf",
                "xps document writer",
            )
        )

    def _resolve_selected_printer(self, printer: str) -> str:
        if printer != "Impresora predeterminada" or platform.system() != "Windows":
            return printer

        try:
            win32print = importlib.import_module("win32print")
            return win32print.GetDefaultPrinter()
        except Exception:
            return printer

    def _ensure_print_save_picker(self) -> None:
        if not hasattr(self, '_print_save_picker'):
            self._print_save_picker = ft.FilePicker(on_result=self._on_print_save_result)
        if self._print_save_picker not in self.page_ref.overlay:
            self.page_ref.overlay.append(self._print_save_picker)
            self.page_ref.update()

    def _on_print_save_result(self, e: ft.FilePickerResultEvent) -> None:
        temp_path = getattr(self, '_pending_print_temp_path', None)
        self._pending_print_temp_path = None

        if not temp_path:
            return

        try:
            if not e.path:
                self._notify_print("Guardado cancelado.")
                return

            shutil.copyfile(temp_path, e.path)
            self._notify_print(f"PDF guardado como: {Path(e.path).name}")
        except Exception as ex:
            print(f"Error guardando PDF para impresión: {ex}")
            self._notify_print("No se pudo guardar el PDF de impresión.", error=True)
        finally:
            self._schedule_temp_file_deletion(temp_path, delay_seconds=0.0)

    def _build_and_show_print_dialog(self) -> None:
        printers = self._get_system_printers()
        
        # State variables for the dialog
        self._print_range_opt = "all"  # "all", "current", "custom"
        self._print_custom_range = ""
        self._print_selected_printer = printers[0]

        # UI Components
        printer_dropdown = ft.Dropdown(
            label="Destino",
            options=[ft.dropdown.Option(p) for p in printers],
            value=printers[0],
            width=300,
            on_change=lambda e: setattr(self, '_print_selected_printer', e.control.value)
        )

        range_radio = ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value="all", label="Todas las páginas"),
                ft.Radio(value="current", label="Página actual"),
                ft.Radio(value="custom", label="Rango personalizado (ej. 1-5, 8)"),
            ]),
            value="all",
            on_change=self._on_print_range_change
        )
        
        self._custom_range_field = ft.TextField(
            label="Páginas a imprimir",
            hint_text="Ej: 1, 3-5",
            value="",
            disabled=True,
            width=300,
            on_change=lambda e: setattr(self, '_print_custom_range', e.control.value)
        )

        # Preview area: we show a small image of the current page as placeholder
        current_img_src = None
        if hasattr(self, '_page_images') and self.current_page < len(self._page_images):
            img_control = self._page_images[self.current_page]
            if img_control and img_control.src_base64:
                current_img_src = img_control.src_base64

        if current_img_src:
            preview_content = ft.Image(
                src_base64=current_img_src,
                fit=ft.ImageFit.CONTAIN,
                width=200,
                height=280,
                border_radius=ft.border_radius.all(4),
            )
        else:
            preview_content = ft.Column(
                [
                    ft.Icon(ft.Icons.PICTURE_AS_PDF, size=40, color=ft.Colors.GREY_400),
                    ft.Text("Vista no disponible", color=ft.Colors.GREY, size=12)
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER
            )
        
        is_night = getattr(self, '_night_mode', False)
        preview_container = ft.Container(
            content=preview_content,
            alignment=ft.alignment.center,
            bgcolor="#2C2C2C" if is_night else "#E0E0E0",
            padding=10,
            border_radius=ft.border_radius.all(8),
            width=220,
            height=300,
        )

        dialog_content = ft.Row([
            # Left: Settings
            ft.Column([
                ft.Text("Imprimir Documento", size=20, weight=ft.FontWeight.BOLD),
                printer_dropdown,
                ft.Divider(),
                ft.Text("Páginas", weight=ft.FontWeight.W_500),
                range_radio,
                self._custom_range_field,
                ft.Divider(),
                ft.TextButton(
                    icon=ft.Icons.PRINT_OUTLINED,
                    text="Imprimir con la app",
                    on_click=lambda e: self._execute_print()
                )
            ], width=320, spacing=15),
            
            # Right: Preview
            ft.Column([
                ft.Text("Vista Previa (Página Actual)", weight=ft.FontWeight.W_500),
                preview_container
            ], width=240, alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        ], vertical_alignment=ft.CrossAxisAlignment.START, width=580)

        self._print_dialog = ft.AlertDialog(
            content=dialog_content,
            actions=[
                ft.TextButton("Cancelar", on_click=lambda e: self._close_print_dialog()),
                ft.ElevatedButton("Imprimir", on_click=lambda e: self._execute_print(), bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            content_padding=20,
        )

        self.page_ref.overlay.append(self._print_dialog)
        self._print_dialog.open = True
        self.page_ref.update()

    def _on_print_range_change(self, e) -> None:
        self._print_range_opt = e.control.value
        self._custom_range_field.disabled = (self._print_range_opt != "custom")
        self.page_ref.update()

    def _close_print_dialog(self) -> None:
        if hasattr(self, '_print_dialog'):
            self._print_dialog.open = False
            self.page_ref.update()
            if self._print_dialog in self.page_ref.overlay:
                self.page_ref.overlay.remove(self._print_dialog)
            del self._print_dialog

    def _execute_print(self, use_native: bool = False) -> None:
        self._close_print_dialog()
        
        pages_to_print = []
        if self._print_range_opt == "all":
            pages_to_print = list(range(len(self.doc)))
        elif self._print_range_opt == "current":
            pages_to_print = [self.current_page]
        elif self._print_range_opt == "custom":
            pages_to_print = self._parse_page_range(self._print_custom_range, len(self.doc))
        
        if not pages_to_print:
            self._notify_print("Rango de páginas inválido.", error=True)
            return

        self._notify_print("Preparando documento...")

        effective_printer = self._resolve_selected_printer(self._print_selected_printer)
        interactive_printer = self._printer_requires_interaction(effective_printer)

        # Extraer páginas en el hilo principal para evitar segfaults por
        # acceso concurrente al objeto fitz.Document (PyMuPDF)
        temp_path = None
        try:
            temp_pdf = fitz.open()
            if hasattr(self, '_doc_lock'):
                with self._doc_lock:
                    for p in pages_to_print:
                        temp_pdf.insert_pdf(self.doc, from_page=p, to_page=p)
            else:
                for p in pages_to_print:
                    temp_pdf.insert_pdf(self.doc, from_page=p, to_page=p)
            
            temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf", prefix="impresion_")
            os.close(temp_fd)
            temp_pdf.save(temp_path)
            temp_pdf.close()
        except Exception as e:
            print(f"Error creando PDF temporal: {e}")
            self._notify_print("Error preparando el documento.", error=True)
            return

        if platform.system() == "Windows" and interactive_printer:
            self._pending_print_temp_path = temp_path
            self._ensure_print_save_picker()
            suggested_name = f"{Path(self.filename).stem}_impreso.pdf"
            self._notify_print("Seleccione dónde guardar el PDF...")
            self._print_save_picker.save_file(
                dialog_title="Guardar PDF",
                file_name=suggested_name,
                allowed_extensions=["pdf"],
            )
            return

        self._notify_print(f"Enviando a la cola de impresión: {effective_printer}")

        # Run OS print logic in a separate thread to prevent UI blocking
        threading.Thread(
            target=self._print_worker_thread,
            args=(temp_path, effective_printer, use_native),
            daemon=True
        ).start()

    def _print_worker_thread(self, temp_path: str, printer_name: str, use_native: bool) -> None:
        try:
            sys_plat = platform.system()
            
            if sys_plat == "Windows":
                self._handle_windows_print(temp_path, printer_name, use_native)
            else:
                self._handle_unix_print(temp_path, printer_name, use_native, sys_plat)

        except Exception as ex:
            print(f"Error during printing: {ex}")
            self._notify_print("Error interno procesando la impresión.", error=True)
        finally:
            if temp_path:
                self._schedule_temp_file_deletion(temp_path)

    def _handle_windows_print(self, path: str, printer: str, use_native_dlg: bool) -> None:
        win32api = importlib.import_module("win32api")
        win32print = importlib.import_module("win32print")
        
        status = "error"

        if use_native_dlg:
            self._notify_print(
                "El diálogo nativo de Windows no es fiable para PDFs en esta app. Usa 'Imprimir con la app'.",
                error=True,
            )
            return
        else:
            # INTERACCIÓN DIRECTA CON LA API DE IMPRESIÓN (GDI)
            # Evita depender del visor de PDF predeterminado o "printto"
            if self._print_windows_native_gdi(path, printer):
                status = "success"
            else:
                try:
                    # Fallback al verbo "printto"
                    win32api.ShellExecute(0, "printto", path, f'"{printer}"', ".", 0)
                    status = "success"
                except Exception as win_ex:
                    print(f"Advertencia: No se pudo usar printto con win32api: {win_ex}")
                    self._notify_print("No se pudo enviar el PDF a la impresora seleccionada.", error=True)

        if status == "success":
            self._notify_print(f"¡Documento enviado exitosamente a {printer}!")
        elif status == "error":
            self._notify_print("Hubo un problema crítico al intentar imprimir.", error=True)

    def _print_windows_native_gdi(self, path: str, printer_name: str) -> bool:
        """
        Interactúa directamente con la API de Windows GDI para renderizar e imprimir el PDF.
        Esto elimina la dependencia de ShellExecute y visores de terceros.
        """
        try:
            win32print = importlib.import_module("win32print")
            win32ui = importlib.import_module("win32ui")
            win32con = importlib.import_module("win32con")
            from PIL import Image, ImageWin
            import fitz

            if printer_name == "Impresora predeterminada":
                printer_name = win32print.GetDefaultPrinter()

            # 1. Crear el contexto de dispositivo (DC) para la impresora
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(printer_name)

            # 2. Obtener las métricas y capacidades de la impresora seleccionada
            horz_res = hDC.GetDeviceCaps(win32con.HORZRES)  # Ancho imprimible en píxeles
            vert_res = hDC.GetDeviceCaps(win32con.VERTRES)  # Alto imprimible en píxeles

            pdf_doc = fitz.open(path)

            # 3. Iniciar el trabajo de impresión en el spooler de Windows
            hDC.StartDoc("PDF Manager - Impresión")

            for page_index in range(len(pdf_doc)):
                page = pdf_doc.load_page(page_index)
                
                # Renderizar la página PDF a alta resolución (zoom x3)
                zoom = 3.0 
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Convertir Pixmap a una imagen PIL compatible con Windows GDI
                mode = "RGBA" if pix.alpha else "RGB"
                img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                
                # Asegurar fondo blanco si hay transparencia
                if mode == "RGBA":
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[3])
                    img = bg
                
                # 4. Ajustar orientación para que coincida con la impresora
                img_is_landscape = img.width > img.height
                printer_is_landscape = horz_res > vert_res
                
                if img_is_landscape != printer_is_landscape:
                    img = img.rotate(90, expand=True)
                
                # 5. Calcular escala para llenar la página manteniendo el aspecto
                scale_w = horz_res / img.width
                scale_h = vert_res / img.height
                scale = min(scale_w, scale_h)
                
                new_w = int(img.width * scale)
                new_h = int(img.height * scale)
                
                # Centrar en la página de la impresora
                x_offset = (horz_res - new_w) // 2
                y_offset = (vert_res - new_h) // 2
                
                # 6. Dibujar la imagen directamente en el contexto del dispositivo (DC)
                hDC.StartPage()
                dib = ImageWin.Dib(img)
                dib.draw(hDC.GetHandleOutput(), (x_offset, y_offset, x_offset + new_w, y_offset + new_h))
                hDC.EndPage()
                
            hDC.EndDoc()
            hDC.DeleteDC()
            pdf_doc.close()
            return True
            
        except ImportError as e:
            print(f"Faltan dependencias (Pillow/pywin32) para impresión nativa GDI: {e}")
            return False
        except Exception as e:
            print(f"Error en impresión nativa GDI: {e}")
            return False

    def _handle_unix_print(self, path: str, printer: str, use_native_dlg: bool, sys_plat: str) -> None:
        success = False
        if use_native_dlg:
            if sys_plat == "Darwin":
                success = subprocess.run(["open", path]).returncode == 0
            else:
                # Linux xdg-open abrirá el visor por defecto
                success = subprocess.run(["xdg-open", path]).returncode == 0
        else:
            cmd = ["lp", "-d", printer, path] if printer != "Impresora predeterminada" else ["lp", path]
            success = subprocess.run(cmd).returncode == 0
        
        if success:
            self._notify_print(f"Documento enviado a impresión: {printer}")
        elif not success:
            self._notify_print("Hubo un problema al intentar imprimir el documento.", error=True)

    def _schedule_temp_file_deletion(self, path: str, delay_seconds: float = 120.0) -> None:
        """Schedules the deletion of a temporary file after a delay."""
        def delayed_delete():
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                print(f"No se pudo eliminar el archivo temporal {path}: {e}")
        
        t = threading.Timer(delay_seconds, delayed_delete)
        t.daemon = True
        t.start()

    def _parse_page_range(self, range_str: str, total_pages: int) -> list[int]:
        pages = set()
        parts = [p.strip() for p in range_str.split(',') if p.strip()]
        for part in parts:
            if '-' in part:
                try:
                    start, end = part.split('-')
                    start_idx = max(0, int(start) - 1)
                    end_idx = min(total_pages - 1, int(end) - 1)
                    if start_idx <= end_idx:
                        pages.update(range(start_idx, end_idx + 1))
                except ValueError:
                    continue
            else:
                try:
                    idx = int(part) - 1
                    if 0 <= idx < total_pages:
                        pages.add(idx)
                except ValueError:
                    continue
        return sorted(list(pages))
