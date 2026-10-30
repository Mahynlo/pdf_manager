"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.page_ranges``.

Se registra con el mismo objeto, así ``import page_ranges`` y ``import pdf_core.page_ranges`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core import page_ranges as _module

sys.modules[__name__] = _module
