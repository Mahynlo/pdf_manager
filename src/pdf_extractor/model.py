"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.extractor.model``.

Se registra con el mismo objeto, así ``import pdf_extractor.model`` y ``import pdf_core.extractor.model`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core.extractor import model as _module

sys.modules[__name__] = _module
