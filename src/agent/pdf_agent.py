"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.agent.pdf_agent``.

Se registra con el mismo objeto. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core.agent import pdf_agent as _module

sys.modules[__name__] = _module
