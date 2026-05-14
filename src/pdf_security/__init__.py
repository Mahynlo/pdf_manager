"""PDF Security module: unlock password-protected PDFs and display permissions."""

from .security import PDFSecurityManager
from .tab import PDFSecurityTab

__all__ = ["PDFSecurityManager", "PDFSecurityTab"]
