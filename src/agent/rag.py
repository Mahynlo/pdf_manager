"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.agent.rag``.

Se registra con el mismo objeto. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core.agent import rag as _module

sys.modules[__name__] = _module
