"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.text_utils``.

Se registra con el mismo objeto, así ``import text_utils`` y ``import pdf_core.text_utils`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core import text_utils as _module

sys.modules[__name__] = _module
