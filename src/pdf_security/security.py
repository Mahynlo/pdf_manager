"""PDF security operations: detection, unlocking, and permission reading."""

from dataclasses import dataclass
from typing import Optional

import fitz


class PDFSecurityError(ValueError):
    """Base exception for PDF security operations."""


class PDFPasswordRequiredError(PDFSecurityError):
    """Raised when an encrypted PDF needs a password to be opened."""


class PDFInvalidPasswordError(PDFSecurityError):
    """Raised when password authentication fails for an encrypted PDF."""


@dataclass
class PDFSecurityInfo:
    """Security information for a PDF document."""
    is_protected: bool
    is_encrypted: bool
    permissions: int
    has_user_password: bool
    has_owner_password: bool
    encryption_method: str
    
    def get_permissions_text(self) -> list[str]:
        """Return human-readable list of allowed operations."""
        perms = []
        
        # PyMuPDF permission constants
        PDF_PERM_PRINT = 4
        PDF_PERM_MODIFY = 8
        PDF_PERM_COPY = 16
        PDF_PERM_ANNOTATE = 32
        PDF_PERM_FORMS = 256
        PDF_PERM_ASSEMBLY = 1024
        PDF_PERM_PRINT_HQ = 2048
        
        if self.permissions & PDF_PERM_PRINT:
            perms.append("✓ Impresión permitida")
        else:
            perms.append("✗ Impresión bloqueada")
            
        if self.permissions & PDF_PERM_MODIFY:
            perms.append("✓ Modificación permitida")
        else:
            perms.append("✗ Modificación bloqueada")
            
        if self.permissions & PDF_PERM_COPY:
            perms.append("✓ Copia de contenido permitida")
        else:
            perms.append("✗ Copia de contenido bloqueada")
            
        if self.permissions & PDF_PERM_ANNOTATE:
            perms.append("✓ Anotaciones permitidas")
        else:
            perms.append("✗ Anotaciones bloqueadas")
            
        if self.permissions & PDF_PERM_FORMS:
            perms.append("✓ Formularios permitidos")
        else:
            perms.append("✗ Formularios bloqueados")
            
        if self.permissions & PDF_PERM_ASSEMBLY:
            perms.append("✓ Ensamblaje permitido")
        else:
            perms.append("✗ Ensamblaje bloqueado")
            
        if self.permissions & PDF_PERM_PRINT_HQ:
            perms.append("✓ Impresión de alta calidad permitida")
        else:
            perms.append("✗ Impresión de alta calidad bloqueada")
        
        return perms if perms else ["No hay permisos definidos"]


class PDFSecurityManager:
    """Manages PDF security operations: detection, unlocking, creation, and metadata."""
    
    # Permission constants
    PDF_PERM_PRINT = 4
    PDF_PERM_MODIFY = 8
    PDF_PERM_COPY = 16
    PDF_PERM_ANNOTATE = 32
    PDF_PERM_FORMS = 256
    PDF_PERM_ASSEMBLY = 1024
    PDF_PERM_PRINT_HQ = 2048

    @staticmethod
    def _has_permission(permissions: int, *flags: int) -> bool:
        """Return True when any provided permission flag is present."""
        if permissions < 0:
            return True
        return any(bool(permissions & flag) for flag in flags)
    
    @staticmethod
    def get_security_info(path: str) -> PDFSecurityInfo:
        """Get security information about a PDF without opening it."""
        try:
            doc = fitz.open(path)
            is_protected = doc.is_pdf and doc.is_encrypted
            
            info = PDFSecurityInfo(
                is_protected=is_protected,
                is_encrypted=doc.is_encrypted,
                permissions=doc.permissions,
                has_user_password=is_protected,  # User password present if encrypted
                has_owner_password=is_protected,  # Owner password present if encrypted
                encryption_method="PDF Standard Encryption" if is_protected else "None"
            )
            
            doc.close()
            return info
            
        except fitz.FileError as e:
            raise ValueError(f"Error al leer el PDF: {e}")
    
    @staticmethod
    def is_protected(path: str) -> bool:
        """Check if a PDF is password-protected."""
        try:
            doc = fitz.open(path)
            is_protected = doc.is_encrypted
            doc.close()
            return is_protected
        except Exception:
            return False
    
    @staticmethod
    def unlock_pdf(path: str, password: str) -> Optional[fitz.Document]:
        """
        Try to unlock a PDF with the given password.
        Returns the opened document if successful, None otherwise.
        """
        try:
            doc = fitz.open(path)
            
            # Try to authenticate with the password
            if not doc.is_encrypted:
                return doc
            
            # Try with user password
            if doc.authenticate(password):
                return doc
            
            # If authentication fails, close and return None
            doc.close()
            return None
            
        except Exception as e:
            raise ValueError(f"Error al desbloquear PDF: {e}")

    @staticmethod
    def open_for_viewer(path: str, password: Optional[str] = None) -> fitz.Document:
        """
        Open a PDF for visualization, authenticating if it is encrypted.

        Returns an opened fitz.Document ready to be used by the viewer.
        Raises ValueError when password is required or invalid.
        """
        doc = None
        try:
            doc = fitz.open(path)

            if not doc.is_encrypted:
                return doc

            if not password:
                raise PDFPasswordRequiredError("PDF protegido requiere contraseña")

            if not doc.authenticate(password):
                raise PDFInvalidPasswordError("Contraseña incorrecta")

            return doc

        except Exception:
            if doc is not None:
                doc.close()
            raise
    
    @staticmethod
    def unlock_pdf_to_file(path: str, password: str, output_path: str) -> bool:
        """
        Unlock a PDF and save it without protection to output_path.
        Returns True if successful.
        """
        doc = None
        try:
            doc = PDFSecurityManager.unlock_pdf(path, password)
            
            if doc is None:
                raise ValueError("Contraseña incorrecta o PDF no se pudo desbloquear")
            
            # Save without encryption
            doc.save(output_path)
            return True
            
        except Exception as e:
            raise ValueError(f"Error al guardar PDF desbloqueado: {e}")
        finally:
            if doc is not None:
                doc.close()
    
    @staticmethod
    def check_permissions(path: str, password: Optional[str] = None) -> PDFSecurityInfo:
        """
        Get detailed permission information for a PDF.
        If the PDF is encrypted, password must be provided.
        """
        doc = None
        try:
            doc = fitz.open(path)
            
            if doc.is_encrypted:
                if password is None:
                    raise ValueError("PDF protegido requiere contraseña")
                
                if not doc.authenticate(password):
                    raise ValueError("Contraseña incorrecta")
            
            info = PDFSecurityInfo(
                is_protected=doc.is_encrypted,
                is_encrypted=doc.is_encrypted,
                permissions=doc.permissions,
                has_user_password=doc.is_encrypted,
                has_owner_password=doc.is_encrypted,
                encryption_method="AES" if doc.is_encrypted else "None"
            )
            
            return info
            
        except Exception:
            raise
        finally:
            if doc is not None:
                doc.close()

    @staticmethod
    def can_save_changes(doc: fitz.Document) -> bool:
        """
        Return whether the current opened document has enough permissions to save edits.
        """
        if not doc.is_encrypted:
            return True

        return PDFSecurityManager._has_permission(
            doc.permissions,
            PDFSecurityManager.PDF_PERM_MODIFY,
            PDFSecurityManager.PDF_PERM_ANNOTATE,
            PDFSecurityManager.PDF_PERM_ASSEMBLY,
            PDFSecurityManager.PDF_PERM_FORMS,
        )
    
    @staticmethod
    def protect_pdf(
        input_path: str,
        output_path: str,
        user_password: str,
        owner_password: Optional[str] = None,
        permissions: int = 0
    ) -> bool:
        """
        Protect a PDF with a password and optionally restrict permissions.
        
        Args:
            input_path: Path to the PDF to protect
            output_path: Path where to save the protected PDF
            user_password: Password required to open the PDF
            owner_password: Password to change security settings (optional)
            permissions: Bitwise combination of permission flags
                        If 0, no permissions are set (most restrictive)
                        Use PDFSecurityManager.PDF_PERM_* constants
        
        Returns:
            True if successful
        
        Example:
            PDFSecurityManager.protect_pdf(
                "document.pdf",
                "document_protected.pdf",
                user_password="pass123",
                owner_password="adminpass",
                permissions=PDFSecurityManager.PDF_PERM_PRINT | 
                            PDFSecurityManager.PDF_PERM_COPY
            )
        """
        doc = None
        try:
            doc = fitz.open(input_path)
            
            # Set encryption with permissions
            # If permissions is 0, all operations are restricted
            doc.set_encryption(
                user_password=user_password,
                owner_password=owner_password,
                permissions=permissions
            )
            
            # Save the protected PDF
            doc.save(output_path)
            return True
            
        except Exception as e:
            raise ValueError(f"Error al proteger PDF: {e}")
        finally:
            if doc is not None:
                doc.close()
    
    @staticmethod
    def protect_pdf_with_permissions(
        input_path: str,
        output_path: str,
        user_password: str,
        owner_password: Optional[str] = None,
        allow_print: bool = False,
        allow_modify: bool = False,
        allow_copy: bool = False,
        allow_annotate: bool = False,
        allow_forms: bool = False,
        allow_assembly: bool = False,
        allow_print_hq: bool = False
    ) -> bool:
        """
        Protect a PDF with specific permission flags.
        
        Args:
            input_path: Path to the PDF to protect
            output_path: Path where to save the protected PDF
            user_password: Password required to open the PDF
            owner_password: Password to change security settings
            allow_print: Allow printing
            allow_modify: Allow content modification
            allow_copy: Allow copying content
            allow_annotate: Allow annotations
            allow_forms: Allow filling forms
            allow_assembly: Allow page assembly
            allow_print_hq: Allow high-quality printing
        
        Returns:
            True if successful
        """
        permissions = 0
        
        if allow_print:
            permissions |= PDFSecurityManager.PDF_PERM_PRINT
        if allow_modify:
            permissions |= PDFSecurityManager.PDF_PERM_MODIFY
        if allow_copy:
            permissions |= PDFSecurityManager.PDF_PERM_COPY
        if allow_annotate:
            permissions |= PDFSecurityManager.PDF_PERM_ANNOTATE
        if allow_forms:
            permissions |= PDFSecurityManager.PDF_PERM_FORMS
        if allow_assembly:
            permissions |= PDFSecurityManager.PDF_PERM_ASSEMBLY
        if allow_print_hq:
            permissions |= PDFSecurityManager.PDF_PERM_PRINT_HQ
        
        return PDFSecurityManager.protect_pdf(
            input_path,
            output_path,
            user_password,
            owner_password,
            permissions
        )
    
    @staticmethod
    def change_pdf_permissions(
        input_path: str,
        output_path: str,
        current_owner_password: str,
        new_user_password: Optional[str] = None,
        new_owner_password: Optional[str] = None,
        permissions: Optional[int] = None
    ) -> bool:
        """
        Change the permissions of an already protected PDF.
        
        Args:
            input_path: Path to the protected PDF
            output_path: Path where to save the modified PDF
            current_owner_password: Current owner password
            new_user_password: New user password (if None, keeps current)
            new_owner_password: New owner password (if None, keeps current)
            permissions: New permissions (if None, keeps current)
        
        Returns:
            True if successful
        """
        doc = None
        try:
            doc = fitz.open(input_path)
            
            if doc.is_encrypted:
                if not doc.authenticate(current_owner_password):
                    raise ValueError("Contraseña de propietario incorrecta")
            
            # Use provided values or keep current
            user_pwd = new_user_password if new_user_password is not None else ""
            owner_pwd = new_owner_password if new_owner_password is not None else ""
            perms = permissions if permissions is not None else doc.permissions
            
            doc.set_encryption(
                user_password=user_pwd,
                owner_password=owner_pwd,
                permissions=perms
            )
            
            doc.save(output_path)
            return True
            
        except Exception as e:
            raise ValueError(f"Error al cambiar permisos: {e}")
        finally:
            if doc is not None:
                doc.close()
    
    @staticmethod
    def remove_protection(
        input_path: str,
        output_path: str,
        owner_password: str
    ) -> bool:
        """
        Remove password protection from a PDF entirely.
        Requires the owner password.
        
        Args:
            input_path: Path to the protected PDF
            output_path: Path where to save the unprotected PDF
            owner_password: Owner password to remove protection
        
        Returns:
            True if successful
        """
        doc = None
        try:
            doc = fitz.open(input_path)
            
            if not doc.is_encrypted:
                # Already unprotected, just save a copy
                doc.save(output_path)
                return True
            
            if not doc.authenticate(owner_password):
                raise ValueError("Contraseña de propietario incorrecta")
            
            # Remove encryption by setting empty passwords and full permissions
            doc.set_encryption(
                user_password="",
                owner_password="",
                permissions=-1  # All permissions
            )
            
            doc.save(output_path)
            return True
            
        except Exception as e:
            raise ValueError(f"Error al remover protección: {e}")
        finally:
            if doc is not None:
                doc.close()
    
    @staticmethod
    def get_default_permissions() -> dict:
        """Get a dictionary of default permission presets."""
        return {
            "sin_restricciones": {
                "allow_print": True,
                "allow_modify": True,
                "allow_copy": True,
                "allow_annotate": True,
                "allow_forms": True,
                "allow_assembly": True,
                "allow_print_hq": True,
            },
            "solo_lectura": {
                "allow_print": True,
                "allow_modify": False,
                "allow_copy": True,
                "allow_annotate": False,
                "allow_forms": False,
                "allow_assembly": False,
                "allow_print_hq": False,
            },
            "muy_restrictivo": {
                "allow_print": False,
                "allow_modify": False,
                "allow_copy": False,
                "allow_annotate": False,
                "allow_forms": False,
                "allow_assembly": False,
                "allow_print_hq": False,
            },
            "solo_impresion": {
                "allow_print": True,
                "allow_modify": False,
                "allow_copy": False,
                "allow_annotate": False,
                "allow_forms": False,
                "allow_assembly": False,
                "allow_print_hq": True,
            },
            "impresion_y_lectura": {
                "allow_print": True,
                "allow_modify": False,
                "allow_copy": True,
                "allow_annotate": False,
                "allow_forms": False,
                "allow_assembly": False,
                "allow_print_hq": True,
            }
        }
