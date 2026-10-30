"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.merge.engine``.

Se registra con el mismo objeto, así ``import pdf_merge.engine`` y ``import pdf_core.merge.engine`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core.merge import engine as _module

sys.modules[__name__] = _module
