"""Seguridad de los PDF: detectar el cifrado, desbloquear y leer permisos.

Cifrar lo hace el motor de EmbedPDF en la ventana (``SecurityService.protect``): este PDFium no
sabe escribir el cifrado. Aquí se calcula la máscara de permisos que se le pasa y se comprueba que
las contraseñas nuevas sirven (:func:`password_problem`).
"""

import stringprep
import unicodedata
from dataclasses import dataclass

from pdf_core.pdf import UNRESTRICTED, Document, PasswordError, PdfError


class PDFSecurityError(ValueError):
    """Base exception for PDF security operations."""


class PDFPasswordRequiredError(PDFSecurityError):
    """Raised when an encrypted PDF needs a password to be opened."""


class PDFInvalidPasswordError(PDFSecurityError):
    """Raised when password authentication fails for an encrypted PDF."""


class PDFFileError(PDFSecurityError):
    """Raised when the file cannot be read as a PDF (corrupt, missing, etc.)."""


# (bit de permiso, texto si está permitido, texto si está bloqueado)
_PERMISSION_TEXTS: tuple[tuple[int, str, str], ...] = (
    (4, "Impresión permitida", "Impresión bloqueada"),
    (8, "Modificación permitida", "Modificación bloqueada"),
    (16, "Copia de contenido permitida", "Copia de contenido bloqueada"),
    (32, "Anotaciones permitidas", "Anotaciones bloqueadas"),
    (256, "Formularios permitidos", "Formularios bloqueados"),
    (1024, "Ensamblaje permitido", "Ensamblaje bloqueado"),
    (2048, "Impresión de alta calidad permitida", "Impresión de alta calidad bloqueada"),
)


@dataclass
class PDFSecurityInfo:
    """Security information for a PDF document."""
    is_protected: bool
    is_encrypted: bool
    permissions: int | None  # None: no se conocen hasta abrirlo con su contraseña
    has_user_password: bool
    has_owner_password: bool
    encryption_method: str

    def permission_items(self) -> list[tuple[str, bool]]:
        """``(texto, permitido)`` por cada permiso, p. ej. ``("Impresión bloqueada", False)``."""
        if self.permissions is None:
            return []
        return [
            (allowed_text if self.permissions & flag else blocked_text, bool(self.permissions & flag))
            for flag, allowed_text, blocked_text in _PERMISSION_TEXTS
        ]

    def get_permissions_text(self) -> list[str]:
        """Return human-readable list of allowed operations."""
        return [f"{'✓' if allowed else '✗'} {text}" for text, allowed in self.permission_items()]


class PDFSecurityManager:
    """Manages PDF security operations: detection, unlocking and metadata."""

    # Permission constants
    PDF_PERM_PRINT = 4
    PDF_PERM_MODIFY = 8
    PDF_PERM_COPY = 16
    PDF_PERM_ANNOTATE = 32
    PDF_PERM_FORMS = 256
    PDF_PERM_ASSEMBLY = 1024
    PDF_PERM_PRINT_HQ = 2048

    @staticmethod
    def _open(path: str, password: str | None = None) -> Document:
        try:
            return Document.open(path, password)
        except PasswordError:
            raise
        except (PdfError, OSError) as e:
            raise PDFFileError(f"Error al leer el PDF: {e}") from e

    @staticmethod
    def get_security_info(path: str) -> PDFSecurityInfo:
        """Get security information about a PDF without authenticating.

        Un PDF que se abre sin contraseña pero tiene restricciones no está protegido: solo
        tiene permisos de propietario. Los permisos de uno protegido no se conocen hasta abrirlo.
        """
        try:
            with PDFSecurityManager._open(path) as doc:
                return PDFSecurityInfo(False, False, doc.permissions, False, doc.encrypted,
                                       "PDF Standard Encryption" if doc.encrypted else "None")
        except PasswordError:
            return PDFSecurityInfo(True, True, None, True, True, "PDF Standard Encryption")

    @staticmethod
    def is_protected(path: str) -> bool:
        """True si hace falta contraseña para abrirlo; los errores de lectura se propagan."""
        return PDFSecurityManager.get_security_info(path).is_protected

    @staticmethod
    def unlock_pdf(path: str, password: str) -> Document | None:
        """El documento abierto con ``password``, o ``None`` si no es la contraseña."""
        try:
            return Document.open(path, password)
        except PasswordError:
            return None
        except (PdfError, OSError) as e:
            raise ValueError(f"Error al desbloquear PDF: {e}") from e

    @staticmethod
    def open_for_viewer(source: str | bytes, password: str | None = None) -> Document:
        """Abre un PDF para el visor, de disco o de memoria.

        :raises PDFPasswordRequiredError: si hace falta contraseña y no se indicó.
        :raises PDFInvalidPasswordError: si la indicada no es la correcta.
        """
        try:
            return Document.open(source, password)
        except PasswordError as e:
            if not password:
                raise PDFPasswordRequiredError("PDF protegido requiere contraseña") from e
            raise PDFInvalidPasswordError("Contraseña incorrecta") from e

    @staticmethod
    def unlock_pdf_to_file(path: str, password: str, output_path: str) -> bool:
        """Guarda en *output_path* una copia del PDF sin contraseña ni restricciones."""
        doc = PDFSecurityManager.unlock_pdf(path, password)
        if doc is None:
            raise PDFInvalidPasswordError("Contraseña incorrecta o PDF no se pudo desbloquear")
        try:
            with open(output_path, "wb") as out:
                out.write(doc.to_bytes(decrypt=True))
            return True
        except OSError as e:
            raise PDFFileError(f"Error al guardar PDF desbloqueado: {e}") from e
        finally:
            doc.close()

    @staticmethod
    def check_permissions(path: str, password: str | None = None) -> PDFSecurityInfo:
        """Permisos reales de la sesión que abre el PDF con *password*."""
        try:
            with PDFSecurityManager._open(path, password) as doc:
                protected = bool(password) and doc.encrypted
                return PDFSecurityInfo(protected, protected, doc.permissions, protected, doc.encrypted,
                                       "AES" if doc.encrypted else "None")
        except PasswordError as e:
            if password is None:
                raise PDFPasswordRequiredError("PDF protegido requiere contraseña") from e
            raise PDFInvalidPasswordError("Contraseña incorrecta") from e

    @staticmethod
    def can_save_changes(doc: Document) -> bool:
        """True si el documento abierto permite guardar cambios."""
        permissions = doc.permissions
        if permissions == UNRESTRICTED:
            return True
        flags = (PDFSecurityManager.PDF_PERM_MODIFY, PDFSecurityManager.PDF_PERM_ANNOTATE,
                 PDFSecurityManager.PDF_PERM_ASSEMBLY, PDFSecurityManager.PDF_PERM_FORMS)
        return any(permissions & flag for flag in flags)

    @staticmethod
    def permission_mask(
        allow_print: bool = False,
        allow_modify: bool = False,
        allow_copy: bool = False,
        allow_annotate: bool = False,
        allow_forms: bool = False,
        allow_assembly: bool = False,
        allow_print_hq: bool = False,
    ) -> int:
        """Bits de permiso de un PDF para cifrarlo con esos permisos."""
        manager = PDFSecurityManager
        flags = (
            (allow_print, manager.PDF_PERM_PRINT), (allow_modify, manager.PDF_PERM_MODIFY),
            (allow_copy, manager.PDF_PERM_COPY), (allow_annotate, manager.PDF_PERM_ANNOTATE),
            (allow_forms, manager.PDF_PERM_FORMS), (allow_assembly, manager.PDF_PERM_ASSEMBLY),
            (allow_print_hq, manager.PDF_PERM_PRINT_HQ),
        )
        return sum(flag for allowed, flag in flags if allowed)

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


# ── Contraseñas nuevas ────────────────────────────────────────────────────────
MAX_PASSWORD_BYTES = 127  # AES-256 (revisión 6) usa los primeros 127 bytes en UTF-8: el resto no cuenta


def password_problem(password: str) -> str | None:
    """Por qué ``password`` no sirve para cifrar un PDF, o ``None`` si sirve.

    El cifrado AES-256 de PDF (ISO 32000-2, revisión 6) prepara la contraseña con SASLprep
    (RFC 4013), con las tablas de Unicode 3.2 de ``stringprep``. Un carácter que SASLprep no
    admite (emojis y otros símbolos posteriores, controles, invisibles…) puede hacer que otro
    lector, como Acrobat, no abra el PDF, y los invisibles ni siquiera se ven al escribirla. Solo
    se comprueban las contraseñas que se crean: para abrir un PDF vale la que tenga.
    """
    if not password:
        return "La contraseña está vacía."
    invisible = [c for c in password if stringprep.in_table_b1(c)]
    mapped = "".join(" " if stringprep.in_table_c12(c) else c for c in password if not stringprep.in_table_b1(c))
    text = unicodedata.normalize("NFKC", mapped)
    if invisible or any(_prohibited(c) for c in text):
        return "La contraseña tiene caracteres de control o invisibles. Escríbela de nuevo sin pegarla."
    if any(stringprep.in_table_a1(c) for c in text):
        return "La contraseña no puede llevar emojis ni símbolos especiales: otros lectores de PDF no podrían abrirlo."
    if any(stringprep.in_table_d1(c) for c in text) and (
        any(stringprep.in_table_d2(c) for c in text)
        or not (stringprep.in_table_d1(text[0]) and stringprep.in_table_d1(text[-1]))
    ):
        return "La contraseña mezcla escritura de derecha a izquierda (árabe, hebreo) con otra: usa solo una."
    if text != password:
        # El motor cifra la contraseña tal cual; un lector que la normalice leería otra.
        return ("La contraseña tiene caracteres que otros lectores leen distinto (espacios especiales o letras "
                "de ancho completo). Escríbela de nuevo con el teclado.")
    if len(text.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"La contraseña es demasiado larga: como mucho {MAX_PASSWORD_BYTES} bytes (unos 100 caracteres)."
    return None


def _prohibited(char: str) -> bool:
    """Prohibidos por SASLprep (RFC 4013, 2.3), salvo el espacio no ASCII, que se cambia por uno normal."""
    return any(check(char) for check in (
        stringprep.in_table_c21_c22, stringprep.in_table_c3, stringprep.in_table_c4, stringprep.in_table_c5,
        stringprep.in_table_c6, stringprep.in_table_c7, stringprep.in_table_c8, stringprep.in_table_c9,
    ))
