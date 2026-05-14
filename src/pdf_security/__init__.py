"""PDF Security module: unlock password-protected PDFs and display permissions."""

from .security import (
	PDFInvalidPasswordError,
	PDFPasswordRequiredError,
	PDFSecurityError,
	PDFSecurityManager,
)
from .tab import PDFSecurityTab

__all__ = [
	"PDFSecurityManager",
	"PDFSecurityTab",
	"PDFSecurityError",
	"PDFPasswordRequiredError",
	"PDFInvalidPasswordError",
]
