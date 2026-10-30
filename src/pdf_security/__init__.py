"""PDF Security module: unlock password-protected PDFs and display permissions.

``PDFSecurityTab`` (interfaz Flet) se importa de forma diferida para que la
lógica de ``security`` pueda usarse sin cargar Flet.
"""

from .security import (
	PDFFileError,
	PDFInvalidPasswordError,
	PDFOwnerRequiredError,
	PDFPasswordRequiredError,
	PDFSecurityError,
	PDFSecurityManager,
)

__all__ = [
	"PDFSecurityManager",
	"PDFSecurityTab",
	"PDFSecurityError",
	"PDFPasswordRequiredError",
	"PDFInvalidPasswordError",
	"PDFOwnerRequiredError",
	"PDFFileError",
]


def __getattr__(name: str):
	if name == "PDFSecurityTab":
		from .tab import PDFSecurityTab

		return PDFSecurityTab
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
