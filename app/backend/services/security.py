"""Servicio ``security`` (Seguridad): analizar, desbloquear y proteger PDFs.

Envuelve ``pdf_core.security``. No guarda estado: el frontend envía la ruta en cada llamada.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.backend.host import Host
from app.backend.rpc import UserError, exposed
from app.backend.services.documents import DocumentService
from pdf_core.security import PDFSecurityError, PDFSecurityInfo, PDFSecurityManager

# Permisos que se pueden conceder al proteger (clave del motor, texto de la casilla).
PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("allow_print", "Permitir impresión (calidad estándar)"),
    ("allow_modify", "Permitir modificación de contenido"),
    ("allow_copy", "Permitir copiar/extraer texto e imágenes"),
    ("allow_annotate", "Permitir agregar comentarios y anotaciones"),
    ("allow_forms", "Permitir llenar formularios"),
    ("allow_assembly", "Permitir reorganizar y eliminar páginas"),
    ("allow_print_hq", "Permitir impresión de alta calidad"),
)

# Niveles rápidos en el orden del desplegable (clave del motor, texto).
PRESETS: tuple[tuple[str, str], ...] = (
    ("sin_restricciones", "📖 Sin restricciones - Acceso completo a todo"),
    ("solo_lectura", "🔒 Solo lectura - Ver sin editar ni copiar"),
    ("solo_impresion", "Solo impresión - Imprimir sin copiar a otro programa"),
    ("impresion_y_lectura", "Impresión y lectura - Leer e imprimir, no editar"),
    ("muy_restrictivo", "🔐 Muy restrictivo - Acceso mínimo, solo lectura básica"),
)
DEFAULT_PRESET = "solo_lectura"


def _file_info(path: str) -> dict[str, str]:
    return {"path": path, "name": Path(path).name}


def _suggested(path: str, suffix: str) -> str:
    p = Path(path)
    return str(p.parent / f"{p.stem}_{suffix}{p.suffix}")


class SecurityService:
    def __init__(self, host: Host, documents: DocumentService) -> None:
        self._host = host
        self._documents = documents

    @exposed
    def options(self) -> dict[str, Any]:
        """Permisos y niveles rápidos para construir el formulario «Proteger»."""
        presets = PDFSecurityManager.get_default_permissions()
        return {
            "permissions": [{"key": k, "label": label} for k, label in PERMISSIONS],
            "presets": [{"key": k, "label": label, "values": presets[k]} for k, label in PRESETS],
            "default_preset": DEFAULT_PRESET,
        }

    # ── Desbloquear ──────────────────────────────────────────────────────────
    @exposed
    def pick_protected(self) -> dict[str, Any] | None:
        path = self._host.pick_pdf()
        return self.inspect(path) if path else None

    @exposed
    def inspect(self, path: str, password: str | None = None) -> dict[str, Any]:
        """Estado de seguridad del PDF; con ``password`` muestra los permisos reales."""
        try:
            info = (
                PDFSecurityManager.check_permissions(path, password)
                if password
                else PDFSecurityManager.get_security_info(path)
            )
        except PDFSecurityError as ex:
            raise UserError(str(ex), "security") from ex
        return {**_file_info(path), **self._info_state(info), "authenticated": bool(password)}

    @staticmethod
    def _info_state(info: PDFSecurityInfo) -> dict[str, Any]:
        return {
            "protected": info.is_protected,
            "encryption": info.encryption_method if info.is_encrypted else None,
            "permissions": [{"label": text, "allowed": ok} for text, ok in info.permission_items()],
        }

    @exposed
    def unlock(self, path: str, password: str) -> dict[str, Any]:
        """Comprueba la contraseña, abre el PDF en el visor y devuelve los permisos reales."""
        if not password:
            raise UserError("Ingresa la contraseña", "empty_password")
        try:
            doc = PDFSecurityManager.unlock_pdf(path, password)
        except ValueError as ex:
            raise UserError(str(ex), "security") from ex
        if doc is None:
            raise UserError("Contraseña incorrecta", "invalid_password")
        doc.close()
        state = self.inspect(path, password)
        self._documents.open(path, password)
        return state

    @exposed
    def export_unlocked(self, path: str, password: str = "") -> str | None:
        """Guarda una copia sin contraseña; devuelve la ruta o ``None`` si se cancela."""
        try:
            protected = PDFSecurityManager.is_protected(path)
        except PDFSecurityError as ex:
            raise UserError(str(ex), "security") from ex
        if protected and not password:
            raise UserError("Ingresa la contraseña para poder exportar", "empty_password")
        dest = self._host.save_pdf(_suggested(path, "desbloqueado"))
        if not dest:
            return None
        try:
            if protected:
                PDFSecurityManager.unlock_pdf_to_file(path, password, dest)
            else:
                shutil.copy(path, dest)
        except PDFSecurityError as ex:
            raise UserError(f"Error al guardar: {ex}", "security") from ex
        return dest

    # ── Proteger ─────────────────────────────────────────────────────────────
    @exposed
    def pick_unprotected(self) -> dict[str, str] | None:
        path = self._host.pick_pdf()
        return _file_info(path) if path else None

    @exposed
    def protect(
        self, path: str, user_password: str, owner_password: str, permissions: dict[str, bool]
    ) -> str | None:
        """Cifra con AES-256 y los permisos marcados; devuelve la ruta o ``None`` si se cancela."""
        if not user_password:
            raise UserError("Ingresa una contraseña para el documento", "empty_password")
        dest = self._host.save_pdf(_suggested(path, "protegido"))
        if not dest:
            return None
        allowed = {key: bool(permissions.get(key)) for key, _ in PERMISSIONS}
        try:
            PDFSecurityManager.protect_pdf_with_permissions(
                path, dest, user_password=user_password, owner_password=owner_password or None, **allowed
            )
        except ValueError as ex:
            raise UserError(str(ex), "protect_failed") from ex
        return dest
