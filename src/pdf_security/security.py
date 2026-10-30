"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.security``.

Se registra con el mismo objeto, así ``import pdf_security.security`` y ``import pdf_core.security`` son
el mismo módulo. Se borrará al retirar las versiones Flet y Qt.
"""

import sys

from pdf_core import security as _module

sys.modules[__name__] = _module
