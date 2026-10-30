"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.recent_files``.

Se registra con el mismo objeto, así ``import recent_files`` y ``import pdf_core.recent_files`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core import recent_files as _module

sys.modules[__name__] = _module
