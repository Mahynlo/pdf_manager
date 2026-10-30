"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.extractor.engine``.

Se registra con el mismo objeto, así ``import pdf_extractor.engine`` y ``import pdf_core.extractor.engine`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core.extractor import engine as _module

sys.modules[__name__] = _module
