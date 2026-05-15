from pathlib import Path
import flet as ft
from typing import Optional, Callable, Any

from .security import PDFSecurityManager, PDFSecurityInfo

class PDFSecurityTab:
    """Tab for unlocking/creating/managing password-protected PDFs."""
    
    def __init__(self, page: ft.Page, on_pdf_unlocked: Callable[..., Any], on_close: Optional[Callable[..., Any]] = None):
        self.page = page
        self.on_pdf_unlocked = on_pdf_unlocked
        self._on_close = on_close
        
        # Current state for unlocking
        self.protected_pdf_path: Optional[str] = None
        self.security_info: Optional[PDFSecurityInfo] = None
        
        # Current state for protecting
        self.unprotected_pdf_path: Optional[str] = None
        
        # Presets
        self.presets = PDFSecurityManager.get_default_permissions()
        
        # UI Controls
        self._build_ui()
    
    def _build_ui(self) -> None:
        """Build the security tab UI with two main sections."""
        # File pickers
        self.unlock_file_picker = ft.FilePicker(on_result=self._on_unlock_file_picked)
        self.protect_file_picker = ft.FilePicker(on_result=self._on_protect_file_picked)
        self.page.overlay.append(self.unlock_file_picker)
        self.page.overlay.append(self.protect_file_picker)
        
        # ─── SECTION 1: DESBLOQUEAR ───────────────────────────────────────
        unlock_section = self._build_unlock_section()
        
        # ─── SECTION 2: PROTEGER ───────────────────────────────────────
        protect_section = self._build_protect_section()
        
        # Build main container with two sections using a card and clearer header
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SECURITY, size=32, color="#F9A825"),
                    ft.Column([
                        ft.Text("Gestión de Seguridad de PDFs", size=22, weight="bold", color="#1E2A38"),
                        ft.Text("Desbloquea archivos encriptados y protege tus documentos confidenciales", size=13, color="#666666"),
                    ], spacing=2)
                ],
                alignment="start",
                spacing=16,
            ),
            padding=ft.padding.only(left=20, top=20, right=20, bottom=10)
        )

        tabs_container = ft.Container(
            content=ft.Tabs(
                selected_index=0,
                animation_duration=300,
                tabs=[
                    ft.Tab(
                        tab_content=ft.Row([ft.Icon(ft.Icons.LOCK_OPEN), ft.Text("Desbloquear")]), 
                        content=ft.Container(content=unlock_section, padding=20)
                    ),
                    ft.Tab(
                        tab_content=ft.Row([ft.Icon(ft.Icons.LOCK), ft.Text("Proteger")]), 
                        content=ft.Container(content=protect_section, padding=20)
                    ),
                ],
                expand=True,
            ),
            expand=True,
        )

        self._tab = ft.Card(
            content=ft.Column([header, ft.Divider(height=1, color="#E0E0E0"), tabs_container], spacing=0), 
            elevation=2,
            margin=10
        )
    
    def _build_unlock_section(self) -> ft.Container:
        """Build the unlock section UI."""
        
        select_btn = ft.ElevatedButton(
            "Seleccionar PDF Protegido",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=lambda _: self.unlock_file_picker.pick_files(
                allowed_extensions=["pdf"],
                dialog_title="Seleccionar PDF Protegido"
            ),
            style=ft.ButtonStyle(padding=20)
        )
        
        self.unlock_file_info_text = ft.Text("No hay PDF seleccionado", size=13, color="#999999")
        file_info_container = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.PICTURE_AS_PDF, color="#999999"), self.unlock_file_info_text], expand=True),
            padding=15,
            bgcolor="#F5F5F5",
            border_radius=8,
        )
        
        self.unlock_security_info_column = ft.Column(spacing=6, visible=False)
        security_info_card = ft.Container(
            content=self.unlock_security_info_column,
            padding=15,
            border=ft.border.all(1, "#E0E0E0"),
            border_radius=8,
            visible=False
        )
        self.unlock_security_card_ref = security_info_card
        
        self.unlock_password_field = ft.TextField(
            label="Contraseña del Documento",
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.Icons.PASSWORD,
            width=300,
            visible=False,
            border_color="#1E2A38",
            on_submit=lambda _: self._try_unlock()
        )
        
        self.unlock_btn = ft.ElevatedButton(
            "Desbloquear y Abrir",
            icon=ft.Icons.LOCK_OPEN,
            on_click=lambda _: self._try_unlock(),
            visible=False,
            style=ft.ButtonStyle(padding=15)
        )
        
        self.unlock_export_btn = ft.ElevatedButton(
            "Guardar Sin Contraseña",
            icon=ft.Icons.SAVE_ALT,
            on_click=lambda _: self._export_unlocked(),
            visible=False,
            style=ft.ButtonStyle(padding=15)
        )
        
        self.unlock_message_text = ft.Text("", size=13, weight="w500")
        self.unlock_message_container = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.INFO), self.unlock_message_text]),
            padding=10,
            border_radius=8,
            visible=False,
        )
        
        left_col = ft.Column([
            ft.Text("Paso 1: Archivo", weight="bold", size=16, color="#1E2A38"),
            select_btn,
            file_info_container,
        ], spacing=15)

        right_col = ft.Column([
            ft.Text("Paso 2: Acciones", weight="bold", size=16, color="#1E2A38"),
            security_info_card,
            self.unlock_password_field,
            ft.Row([self.unlock_btn, self.unlock_export_btn], spacing=10, wrap=True),
            self.unlock_message_container,
        ], spacing=15)

        return ft.Container(
            content=ft.Row([
                ft.Container(left_col, expand=1, padding=ft.padding.only(right=20)), 
                ft.VerticalDivider(width=1, color="#E0E0E0"),
                ft.Container(right_col, expand=2, padding=ft.padding.only(left=10))
            ], spacing=0, vertical_alignment="start"),
            expand=True,
        )
    
    def _build_protect_section(self) -> ft.Container:
        """Build the protect section UI."""
        
        select_btn = ft.ElevatedButton(
            "Seleccionar PDF a Proteger",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=lambda _: self.protect_file_picker.pick_files(
                allowed_extensions=["pdf"],
                dialog_title="Seleccionar PDF"
            ),
            style=ft.ButtonStyle(padding=20)
        )
        
        self.protect_file_info_text = ft.Text("No hay PDF seleccionado", size=13, color="#999999")
        file_info_container = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.PICTURE_AS_PDF, color="#999999"), self.protect_file_info_text], expand=True),
            padding=15,
            bgcolor="#F5F5F5",
            border_radius=8,
        )
        
        self.protect_password_field = ft.TextField(
            label="Contraseña de Usuario (Para abrir el PDF)",
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.Icons.PASSWORD,
            helper_text="El usuario necesita esta contraseña para abrir y ver el documento",
            expand=True
        )
        
        self.protect_owner_password_field = ft.TextField(
            label="Contraseña de Propietario (Opcional - Administrador)",
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.Icons.ADMIN_PANEL_SETTINGS,
            helper_text="Permite cambiar permisos y eliminar la contraseña de usuario sin necesitar la contraseña original",
            expand=True
        )
        
        preset_options = [
            ft.dropdown.Option("sin_restricciones", "📖 Sin restricciones - Acceso completo a todo"),
            ft.dropdown.Option("solo_lectura", "🔒 Solo lectura - Ver sin editar ni copiar"),
            ft.dropdown.Option("solo_impresion", "🖨️ Solo impresión - Imprimir sin copiar a otro programa"),
            ft.dropdown.Option("impresion_y_lectura", "📋 Impresión y lectura - Leer e imprimir, no editar"),
            ft.dropdown.Option("muy_restrictivo", "🔐 Muy restrictivo - Acceso mínimo, solo lectura básica"),
        ]
        
        self.protect_preset_dropdown = ft.Dropdown(
            label="Presets rápidos de permisos",
            helper_text="Selecciona un nivel predefinido o personaliza abajo",
            options=preset_options,
            value="solo_lectura",
            icon=ft.Icons.SHIELD
        )
        
        self.protect_allow_print = ft.Checkbox("🖨️ Permitir impresión (cualidad estándar)")
        self.protect_allow_modify = ft.Checkbox("✏️ Permitir modificación de contenido")
        self.protect_allow_copy = ft.Checkbox("📋 Permitir copiar/extraer texto e imágenes")
        self.protect_allow_annotate = ft.Checkbox("💬 Permitir agregar comentarios y anotaciones")
        self.protect_allow_forms = ft.Checkbox("📝 Permitir llenar formularios")
        self.protect_allow_assembly = ft.Checkbox("🔀 Permitir reorganizar y eliminar páginas")
        self.protect_allow_print_hq = ft.Checkbox("🎨 Permitir impresión de alta calidad", value=True)
        
        permissions_section = ft.ExpansionPanel(
            header=ft.ListTile(
                title=ft.Text("Permisos personalizados avanzados", weight="w500"),
                leading=ft.Icon(ft.Icons.TUNE)
            ),
            content=ft.Container(
                content=ft.Column([
                    self.protect_allow_print, self.protect_allow_modify, self.protect_allow_copy,
                    self.protect_allow_annotate, self.protect_allow_forms, self.protect_allow_assembly, self.protect_allow_print_hq,
                ], spacing=2),
                padding=ft.padding.only(left=20, bottom=20, right=20),
                bgcolor="#F5F5F5",
            )
        )
        
        self.protect_btn = ft.ElevatedButton(
            "Cifrar y Guardar PDF",
            icon=ft.Icons.ENHANCED_ENCRYPTION,
            on_click=lambda _: self._protect_pdf(),
            style=ft.ButtonStyle(padding=20)
        )
        
        self.protect_message_text = ft.Text("", size=13, weight="w500")
        self.protect_message_container = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.INFO), self.protect_message_text]),
            padding=10,
            border_radius=8,
            visible=False,
        )
        
        left_col = ft.Column([
            ft.Text("Paso 1: Archivo y Nivel", weight="bold", size=16, color="#1E2A38"),
            select_btn,
            file_info_container,
            ft.Container(height=5),
            self.protect_preset_dropdown,
            ft.ExpansionPanelList(controls=[permissions_section], expand_loose=True, elevation=0),
        ], spacing=15)

        right_col = ft.Column([
            ft.Text("Paso 2: Contraseñas y Permisos", weight="bold", size=16, color="#1E2A38"),
            ft.Text("Define quién puede acceder y qué acciones están permitidas", size=12, color="#666666"),
            ft.Container(height=8),
            
            # Info box explaining both password types
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color="#1565C0"),
                        ft.Text("¿Cuál es la diferencia?", size=13, weight="bold", color="#1565C0")
                    ], spacing=8),
                    ft.Divider(height=10, color="#E0E0E0"),
                    ft.Row([
                        ft.Icon(ft.Icons.PASSWORD, size=16, color="#666666"),
                        ft.Column([
                            ft.Text("Contraseña de Usuario", weight="bold", size=11, color="#1E2A38"),
                            ft.Text("El usuario final la necesita para abrir el PDF. Restringe acciones según los permisos.", size=10, color="#666666")
                        ], tight=True, spacing=2)
                    ], spacing=10),
                    ft.Container(height=8),
                    ft.Row([
                        ft.Icon(ft.Icons.ADMIN_PANEL_SETTINGS, size=16, color="#F9A825"),
                        ft.Column([
                            ft.Text("Contraseña de Propietario", weight="bold", size=11, color="#1E2A38"),
                            ft.Text("Te permite cambiar los permisos y eliminar la contraseña sin necesitar la original.", size=10, color="#666666")
                        ], tight=True, spacing=2)
                    ], spacing=10),
                ], spacing=8, tight=True),
                padding=12,
                bgcolor="#F0F7FF",
                border_radius=8,
                border=ft.border.all(1, "#D0E8FF")
            ),
            
            ft.Container(height=12),
            ft.Row([self.protect_password_field]),
            ft.Row([self.protect_owner_password_field]),
            ft.Container(height=10),
            self.protect_btn,
            self.protect_message_container,
        ], spacing=15)

        return ft.Container(
            content=ft.Row([
                ft.Container(left_col, expand=5, padding=ft.padding.only(right=20)),
                ft.VerticalDivider(width=1, color="#E0E0E0"),
                ft.Container(right_col, expand=4, padding=ft.padding.only(left=10))
            ], spacing=0, vertical_alignment="start"),
            expand=True
        )
    
    # ─── UNLOCK HANDLERS ───────────────────────────────────────────────────
    
    def _on_unlock_file_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        
        path = e.files[0].path
        self.protected_pdf_path = path
        filename = Path(path).name
        
        self.unlock_file_info_text.value = filename
        self.unlock_message_container.visible = False
        
        try:
            is_protected = PDFSecurityManager.is_protected(path)
            
            if is_protected:
                self.unlock_file_info_text.value = f"{filename} (Protegido)"
                self.unlock_password_field.visible = True
                self.unlock_btn.visible = True
                self.unlock_export_btn.visible = True
                self._show_unlock_security_info(path)
            else:
                self.unlock_file_info_text.value = f"{filename} (No protegido)"
                self.unlock_password_field.visible = False
                self.unlock_btn.visible = False
                self.unlock_export_btn.visible = True
                self._show_unlock_security_info(path)
                
        except Exception as ex:
            self._show_unlock_message(f"Error: {ex}", error=True)
            self.unlock_password_field.visible = False
            self.unlock_btn.visible = False
            self.unlock_export_btn.visible = False
            self.unlock_security_card_ref.visible = False
        
        self.page.update()
    
    def _show_unlock_security_info(self, path: str, password: Optional[str] = None) -> None:
        try:
            # If a password is provided, retrieve detailed permissions after authentication
            if password:
                self.security_info = PDFSecurityManager.check_permissions(path, password)
            else:
                self.security_info = PDFSecurityManager.get_security_info(path)
            controls = []
            
            is_prot = self.security_info.is_protected
            status_color = "#D32F2F" if is_prot else "#2E7D32"
            status_icon = ft.Icons.LOCK if is_prot else ft.Icons.LOCK_OPEN
            status_text = "Requiere Contraseña" if is_prot else "Sin Protección"
            
            controls.append(
                ft.Row([
                    ft.Icon(status_icon, color=status_color, size=18),
                    ft.Text(status_text, weight="bold", color=status_color)
                ])
            )
            
            if self.security_info.is_encrypted:
                controls.append(ft.Text(f"Cifrado: {self.security_info.encryption_method}", size=12, color="#666666"))
                if not password:
                    controls.append(ft.Text("Nota: ingresa la contraseña para ver permisos reales.", size=11, color="#9E9E9E"))
            
            controls.append(ft.Divider(height=10, color="#E0E0E0"))
            controls.append(ft.Text("Permisos actuales:", size=12, weight="w500", color="#1E2A38"))
            
            perms = self.security_info.get_permissions_text()
            for perm in perms:
                controls.append(ft.Text(f"• {perm}", size=12, color="#666666"))
            
            self.unlock_security_info_column.controls = controls
            # Make sure the column and its container are visible
            self.unlock_security_info_column.visible = True
            self.unlock_security_card_ref.visible = True
            
        except Exception as ex:
            self._show_unlock_message(f"Error al obtener info: {ex}", error=True)
    
    def _try_unlock(self) -> None:
        if not self.protected_pdf_path:
            self._show_unlock_message("Selecciona un PDF primero", error=True)
            return
        
        password = self.unlock_password_field.value.strip()
        
        if not password:
            self._show_unlock_message("Ingresa la contraseña", error=True)
            return
        
        try:
            doc = PDFSecurityManager.unlock_pdf(self.protected_pdf_path, password)
            if doc is None:
                self._show_unlock_message("Contraseña incorrecta", error=True)
                return
            # Close the opened doc (unlock_pdf returned an authenticated document)
            doc.close()

            # Refresh displayed security info using authenticated permissions
            try:
                self._show_unlock_security_info(self.protected_pdf_path, password)
            except Exception:
                # If fetching detailed permissions fails, continue but inform user
                pass

            self._show_unlock_message("PDF desbloqueado exitosamente", error=False)

            if self.on_pdf_unlocked:
                self.on_pdf_unlocked(self.protected_pdf_path, password)
                
        except Exception as ex:
            self._show_unlock_message(f"Error: {ex}", error=True)
    
    def _export_unlocked(self) -> None:
        if not self.protected_pdf_path:
            self._show_unlock_message("Selecciona un PDF primero", error=True)
            return
        
        password = self.unlock_password_field.value.strip()
        
        try:
            base_path = Path(self.protected_pdf_path)
            output_name = f"{base_path.stem}_desbloqueado{base_path.suffix}"
            output_path = base_path.parent / output_name
            
            if PDFSecurityManager.is_protected(self.protected_pdf_path):
                if not password:
                    self._show_unlock_message("Ingresa la contraseña para poder exportar", error=True)
                    return
                PDFSecurityManager.unlock_pdf_to_file(self.protected_pdf_path, password, str(output_path))
            else:
                import shutil
                shutil.copy(self.protected_pdf_path, str(output_path))
            
            self._show_unlock_message(f"PDF guardado con éxito: {output_name}", error=False)
            
        except Exception as ex:
            self._show_unlock_message(f"Error: {ex}", error=True)
    
    def _show_unlock_message(self, msg: str, error: bool = False) -> None:
        self.unlock_message_text.value = msg
        color = "#D32F2F" if error else "#2E7D32"
        bg_color = "#FFEBEE" if error else "#E8F5E9"
        
        self.unlock_message_text.color = color
        self.unlock_message_container.bgcolor = bg_color
        self.unlock_message_container.content.controls[0].color = color
        self.unlock_message_container.visible = True
        self.page.update()
    
    # ─── PROTECT HANDLERS ───────────────────────────────────────────────────
    
    def _on_protect_file_picked(self, e: ft.FilePickerResultEvent) -> None:
        if not e.files:
            return
        
        path = e.files[0].path
        self.unprotected_pdf_path = path
        filename = Path(path).name
        
        self.protect_file_info_text.value = filename
        self.protect_message_container.visible = False
        self.page.update()
    
    def _protect_pdf(self) -> None:
        if not self.unprotected_pdf_path:
            self._show_protect_message("Selecciona un PDF primero", error=True)
            return
        
        user_password = self.protect_password_field.value.strip()
        owner_password = self.protect_owner_password_field.value.strip() or None
        preset_name = self.protect_preset_dropdown.value
        
        if not user_password:
            self._show_protect_message("Ingresa una contraseña para el documento", error=True)
            return
        
        try:
            base_path = Path(self.unprotected_pdf_path)
            output_name = f"{base_path.stem}_protegido{base_path.suffix}"
            output_path = base_path.parent / output_name
            
            if preset_name in self.presets:
                perm_dict = self.presets[preset_name]
            else:
                perm_dict = {
                    "allow_print": self.protect_allow_print.value,
                    "allow_modify": self.protect_allow_modify.value,
                    "allow_copy": self.protect_allow_copy.value,
                    "allow_annotate": self.protect_allow_annotate.value,
                    "allow_forms": self.protect_allow_forms.value,
                    "allow_assembly": self.protect_allow_assembly.value,
                    "allow_print_hq": self.protect_allow_print_hq.value,
                }
            
            PDFSecurityManager.protect_pdf_with_permissions(
                self.unprotected_pdf_path,
                str(output_path),
                user_password=user_password,
                owner_password=owner_password,
                **perm_dict
            )
            
            self._show_protect_message(f"Documento protegido guardado: {output_name}", error=False)
            
            self.protect_password_field.value = ""
            self.protect_owner_password_field.value = ""
            
        except Exception as ex:
            self._show_protect_message(f"Error: {ex}", error=True)
    
    def _show_protect_message(self, msg: str, error: bool = False) -> None:
        self.protect_message_text.value = msg
        color = "#D32F2F" if error else "#2E7D32"
        bg_color = "#FFEBEE" if error else "#E8F5E9"
        
        self.protect_message_text.color = color
        self.protect_message_container.bgcolor = bg_color
        self.protect_message_container.content.controls[0].color = color
        self.protect_message_container.visible = True
        self.page.update()
    
    # ─── COMMON ───────────────────────────────────────────────────────────
    
    def get_tab_info(self) -> dict:
        info = {
            "label": "Seguridad",
            "icon": ft.Icons.SECURITY,
            "content": self._tab,
            "closeable": True,
        }
        if self._on_close:
            info["close_cb"] = lambda: self._on_close(self)
        return info
    
    def close(self) -> None:
        for picker in (self.unlock_file_picker, self.protect_file_picker):
            try:
                self.page.overlay.remove(picker)
            except ValueError:
                pass
