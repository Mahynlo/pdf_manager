"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.ocr.processor``.

Se registra con el mismo objeto, así ``import pdf_viewer.ocr.processor`` y ``import pdf_core.ocr.processor`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core.ocr import processor as _module

sys.modules[__name__] = _module
