"""PDFSecurityTab: UI for managing password-protected PDFs."""

from pathlib import Path
import flet as ft

from .security import PDFSecurityManager, PDFSecurityInfo


class PDFSecurityTab:
    """Tab for unlocking/creating/managing password-protected PDFs."""
    
    def __init__(self, page: ft.Page, on_pdf_unlocked: callable):
        """
        Initialize the security tab.
        
        Args:
            page: Flet page reference
            on_pdf_unlocked: Callback when PDF is successfully unlocked
        """
        self.page = page
        self.on_pdf_unlocked = on_pdf_unlocked
        
        # Current state for unlocking
        self.protected_pdf_path: str | None = None
        self.security_info: PDFSecurityInfo | None = None
        
        # Current state for protecting
        self.unprotected_pdf_path: str | None = None
        
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
        
        # Build main container with two sections
        self._tab = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Text(
                            "🔐 Gestión de Seguridad de PDFs",
                            size=24,
                            weight="bold",
                            color="#1E2A38"
                        ),
                        padding=20,
                        bgcolor="#F5F5F5",
                    ),
                    ft.Tabs(
                        selected_index=0,
                        tabs=[
                            ft.Tab(
                                text="🔓 Desbloquear",
                                content=unlock_section
                            ),
                            ft.Tab(
                                text="🔒 Proteger",
                                content=protect_section
                            ),
                        ]
                    ),
                ],
                spacing=0,
                expand=True
            ),
            expand=True
        )
    
    def _build_unlock_section(self) -> ft.Container:
        """Build the unlock section UI."""
        # Select PDF button
        select_btn = ft.ElevatedButton(
            "Seleccionar PDF Protegido",
            icon=ft.icons.FOLDER_OPEN,
            on_click=lambda _: self.unlock_file_picker.pick_files(
                allowed_extensions=["pdf"],
                dialog_title="Seleccionar PDF Protegido"
            )
        )
        
        # File info display
        self.unlock_file_info_text = ft.Text(
            "No hay PDF seleccionado",
            size=11,
            color="#999999"
        )
        
        # Security info display
        self.unlock_security_info_column = ft.Column(
            controls=[],
            spacing=8,
            visible=False
        )
        
        # Password input
        self.unlock_password_field = ft.TextField(
            label="Contraseña",
            password=True,
            width=250,
            visible=False,
            on_submit=lambda _: self._try_unlock()
        )
        
        # Buttons
        self.unlock_btn = ft.ElevatedButton(
            "Desbloquear y Abrir",
            icon=ft.icons.LOCK_OPEN,
            on_click=lambda _: self._try_unlock(),
            visible=False
        )
        
        self.unlock_export_btn = ft.ElevatedButton(
            "Guardar Desbloqueado",
            icon=ft.icons.SAVE,
            on_click=lambda _: self._export_unlocked(),
            visible=False
        )
        
        # Error/success messages
        self.unlock_message_text = ft.Text(
            "",
            size=11,
            color="#D32F2F",
            visible=False
        )
        
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Text(
                            "Desbloquea PDFs protegidos con contraseña",
                            size=12,
                            color="#666666",
                            italic=True
                        ),
                        padding=ft.padding.symmetric(horizontal=20, vertical=10),
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                select_btn,
                                ft.Divider(),
                                self.unlock_file_info_text,
                                ft.Container(height=20),
                                self.unlock_security_info_column,
                                ft.Container(height=20),
                                ft.Row(
                                    controls=[
                                        self.unlock_password_field,
                                        ft.Column(
                                            controls=[
                                                self.unlock_btn,
                                                self.unlock_export_btn,
                                            ],
                                            spacing=8
                                        )
                                    ],
                                    spacing=10
                                ),
                                self.unlock_message_text,
                            ],
                            spacing=12
                        ),
                        padding=20,
                        expand=True
                    ),
                ],
                spacing=0,
                expand=True
            ),
            expand=True
        )
    
    def _build_protect_section(self) -> ft.Container:
        """Build the protect section UI."""
        # Select PDF button
        select_btn = ft.ElevatedButton(
            "Seleccionar PDF para Proteger",
            icon=ft.icons.FOLDER_OPEN,
            on_click=lambda _: self.protect_file_picker.pick_files(
                allowed_extensions=["pdf"],
                dialog_title="Seleccionar PDF"
            )
        )
        
        # File info display
        self.protect_file_info_text = ft.Text(
            "No hay PDF seleccionado",
            size=11,
            color="#999999"
        )
        
        # Password input
        self.protect_password_field = ft.TextField(
            label="Contraseña de usuario",
            password=True,
            width=250
        )
        
        self.protect_owner_password_field = ft.TextField(
            label="Contraseña de propietario (opcional)",
            password=True,
            width=250,
            hint_text="Para cambiar permisos después"
        )
        
        # Preset selector
        preset_options = [
            ft.dropdown.Option("sin_restricciones", "Sin restricciones - Acceso completo"),
            ft.dropdown.Option("solo_lectura", "Solo lectura - No puede modificar"),
            ft.dropdown.Option("solo_impresion", "Solo impresión - Sin copia"),
            ft.dropdown.Option("impresion_y_lectura", "Impresión y lectura - Permisos limitados"),
            ft.dropdown.Option("muy_restrictivo", "Muy restrictivo - Solo visor"),
        ]
        
        self.protect_preset_dropdown = ft.Dropdown(
            label="Nivel de protección",
            options=preset_options,
            value="solo_lectura",
            width=300
        )
        
        # Manual permissions
        self.protect_allow_print = ft.Checkbox("Permitir impresión")
        self.protect_allow_modify = ft.Checkbox("Permitir modificación")
        self.protect_allow_copy = ft.Checkbox("Permitir copia de contenido")
        self.protect_allow_annotate = ft.Checkbox("Permitir anotaciones")
        self.protect_allow_forms = ft.Checkbox("Permitir formularios")
        self.protect_allow_assembly = ft.Checkbox("Permitir ensamblaje de páginas")
        self.protect_allow_print_hq = ft.Checkbox("Permitir impresión de alta calidad")
        
        # Protect button
        self.protect_btn = ft.ElevatedButton(
            "Crear PDF Protegido",
            icon=ft.icons.SHIELD,
            on_click=lambda _: self._protect_pdf()
        )
        
        # Error/success messages
        self.protect_message_text = ft.Text(
            "",
            size=11,
            color="#D32F2F",
            visible=False
        )
        
        # Expandable permissions section
        permissions_section = ft.ExpansionPanel(
            header=ft.ListTile(
                title=ft.Text("Permisos personalizados", weight="bold"),
                subtitle=ft.Text("Configurar manualmente")
            ),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        self.protect_allow_print,
                        self.protect_allow_modify,
                        self.protect_allow_copy,
                        self.protect_allow_annotate,
                        self.protect_allow_forms,
                        self.protect_allow_assembly,
                        self.protect_allow_print_hq,
                    ],
                    spacing=8
                ),
                padding=20
            )
        )
        
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Text(
                            "Protege tus PDFs con contraseña y permisos",
                            size=12,
                            color="#666666",
                            italic=True
                        ),
                        padding=ft.padding.symmetric(horizontal=20, vertical=10),
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                select_btn,
                                ft.Divider(),
                                self.protect_file_info_text,
                                ft.Container(height=15),
                                
                                ft.Text("Contraseñas:", size=12, weight="bold"),
                                self.protect_password_field,
                                self.protect_owner_password_field,
                                ft.Container(height=15),
                                
                                ft.Text("Nivel de protección:", size=12, weight="bold"),
                                self.protect_preset_dropdown,
                                ft.Container(height=15),
                                
                                ft.ExpansionPanelList(
                                    controls=[permissions_section],
                                    expand_loose=True
                                ),
                                ft.Container(height=20),
                                
                                self.protect_btn,
                                self.protect_message_text,
                            ],
                            spacing=12,
                            scroll=ft.ScrollMode.AUTO
                        ),
                        padding=20,
                        expand=True
                    ),
                ],
                spacing=0,
                expand=True
            ),
            expand=True
        )
    
    # ─── UNLOCK HANDLERS ───────────────────────────────────────────────────
    
    def _on_unlock_file_picked(self, e: ft.FilePickerResultEvent) -> None:
        """Handle file picker result for unlocking."""
        if not e.files:
            return
        
        path = e.files[0].path
        self.protected_pdf_path = path
        filename = Path(path).name
        
        # Show file info
        self.unlock_file_info_text.value = f"📄 Archivo: {filename}"
        self.unlock_message_text.visible = False
        
        # Check if PDF is protected
        try:
            is_protected = PDFSecurityManager.is_protected(path)
            
            if is_protected:
                self.unlock_file_info_text.value += " 🔒 (Protegido)"
                self.unlock_password_field.visible = True
                self.unlock_btn.visible = True
                self.unlock_export_btn.visible = True
                self._show_unlock_security_info(path)
            else:
                self.unlock_file_info_text.value += " 🔓 (No protegido)"
                self.unlock_password_field.visible = False
                self.unlock_btn.visible = False
                self.unlock_export_btn.visible = True
                self._show_unlock_security_info(path)
                
        except Exception as ex:
            self._show_unlock_message(f"Error: {ex}", error=True)
            self.unlock_password_field.visible = False
            self.unlock_btn.visible = False
            self.unlock_export_btn.visible = False
        
        self.page.update()
    
    def _show_unlock_security_info(self, path: str) -> None:
        """Display security information about the PDF."""
        try:
            self.security_info = PDFSecurityManager.get_security_info(path)
            
            # Build info controls
            controls = []
            
            # Protection status
            status_text = "🔒 Protegido por contraseña" if self.security_info.is_protected else "🔓 Sin protección"
            controls.append(ft.Text(status_text, size=12, weight="bold"))
            
            # Encryption info
            if self.security_info.is_encrypted:
                controls.append(
                    ft.Text(
                        f"Método de cifrado: {self.security_info.encryption_method}",
                        size=11,
                        color="#666666"
                    )
                )
            
            # Permissions header
            controls.append(ft.Text("Permisos:", size=12, weight="bold", color="#1E2A38"))
            
            # Permissions list
            perms = self.security_info.get_permissions_text()
            for perm in perms:
                controls.append(
                    ft.Text(
                        f"  {perm}",
                        size=11,
                        color="#333333"
                    )
                )
            
            self.unlock_security_info_column.controls = controls
            self.unlock_security_info_column.visible = True
            
        except Exception as ex:
            self._show_unlock_message(f"Error al obtener información: {ex}", error=True)
    
    def _try_unlock(self) -> None:
        """Try to unlock the PDF with the entered password."""
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
                self._show_unlock_message("❌ Contraseña incorrecta", error=True)
                return
            
            doc.close()
            
            self._show_unlock_message("✓ PDF desbloqueado exitosamente", error=False)
            
            # Notify callback that PDF is unlocked
            if self.on_pdf_unlocked:
                self.on_pdf_unlocked(self.protected_pdf_path, password)
            
        except Exception as ex:
            self._show_unlock_message(f"Error: {ex}", error=True)
    
    def _export_unlocked(self) -> None:
        """Export the PDF without password protection."""
        if not self.protected_pdf_path:
            self._show_unlock_message("Selecciona un PDF primero", error=True)
            return
        
        password = self.unlock_password_field.value.strip()
        
        try:
            # Generate output filename
            base_path = Path(self.protected_pdf_path)
            output_name = f"{base_path.stem}_desbloqueado{base_path.suffix}"
            output_path = base_path.parent / output_name
            
            if PDFSecurityManager.is_protected(self.protected_pdf_path):
                if not password:
                    self._show_unlock_message("Ingresa la contraseña", error=True)
                    return
                
                PDFSecurityManager.unlock_pdf_to_file(
                    self.protected_pdf_path,
                    password,
                    str(output_path)
                )
            else:
                # Just copy if not protected
                import shutil
                shutil.copy(self.protected_pdf_path, str(output_path))
            
            self._show_unlock_message(
                f"✓ PDF guardado: {output_name}",
                error=False
            )
            
        except Exception as ex:
            self._show_unlock_message(f"Error: {ex}", error=True)
    
    def _show_unlock_message(self, msg: str, error: bool = False) -> None:
        """Display a message in unlock section."""
        self.unlock_message_text.value = msg
        self.unlock_message_text.color = "#D32F2F" if error else "#2E7D32"
        self.unlock_message_text.visible = True
        self.page.update()
    
    # ─── PROTECT HANDLERS ───────────────────────────────────────────────────
    
    def _on_protect_file_picked(self, e: ft.FilePickerResultEvent) -> None:
        """Handle file picker result for protecting."""
        if not e.files:
            return
        
        path = e.files[0].path
        self.unprotected_pdf_path = path
        filename = Path(path).name
        
        self.protect_file_info_text.value = f"📄 Archivo: {filename}"
        self.protect_message_text.visible = False
        self.page.update()
    
    def _protect_pdf(self) -> None:
        """Create a protected copy of the PDF."""
        if not self.unprotected_pdf_path:
            self._show_protect_message("Selecciona un PDF primero", error=True)
            return
        
        user_password = self.protect_password_field.value.strip()
        owner_password = self.protect_owner_password_field.value.strip() or None
        preset_name = self.protect_preset_dropdown.value
        
        if not user_password:
            self._show_protect_message("Ingresa una contraseña", error=True)
            return
        
        try:
            # Generate output filename
            base_path = Path(self.unprotected_pdf_path)
            output_name = f"{base_path.stem}_protegido{base_path.suffix}"
            output_path = base_path.parent / output_name
            
            # Get permissions based on preset
            if preset_name in self.presets:
                perm_dict = self.presets[preset_name]
            else:
                # Use custom permissions
                perm_dict = {
                    "allow_print": self.protect_allow_print.value,
                    "allow_modify": self.protect_allow_modify.value,
                    "allow_copy": self.protect_allow_copy.value,
                    "allow_annotate": self.protect_allow_annotate.value,
                    "allow_forms": self.protect_allow_forms.value,
                    "allow_assembly": self.protect_allow_assembly.value,
                    "allow_print_hq": self.protect_allow_print_hq.value,
                }
            
            # Protect the PDF
            PDFSecurityManager.protect_pdf_with_permissions(
                self.unprotected_pdf_path,
                str(output_path),
                user_password=user_password,
                owner_password=owner_password,
                **perm_dict
            )
            
            self._show_protect_message(
                f"✓ PDF protegido creado: {output_name}",
                error=False
            )
            
            # Reset form
            self.protect_password_field.value = ""
            self.protect_owner_password_field.value = ""
            self.protect_file_info_text.value = "No hay PDF seleccionado"
            
        except Exception as ex:
            self._show_protect_message(f"Error: {ex}", error=True)
    
    def _show_protect_message(self, msg: str, error: bool = False) -> None:
        """Display a message in protect section."""
        self.protect_message_text.value = msg
        self.protect_message_text.color = "#D32F2F" if error else "#2E7D32"
        self.protect_message_text.visible = True
        self.page.update()
    
    # ─── COMMON ───────────────────────────────────────────────────────────
    
    def get_tab_info(self) -> dict:
        """Return tab information for main tab bar."""
        return {
            "text": "🔐 Seguridad",
            "icon": ft.icons.LOCK,
            "content": self._tab,
        }
    
    def close(self) -> None:
        """Cleanup when tab is closed."""
        pass
