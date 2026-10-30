"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.legends``.

Se registra con el mismo objeto, así ``import pdf_viewer._text_legends`` y ``import pdf_core.legends`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core import legends as _module

sys.modules[__name__] = _module
