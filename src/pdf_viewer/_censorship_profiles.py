"""Compatibilidad (Flet/Qt): este módulo vive en ``pdf_core.censorship_profiles``.

Se registra con el mismo objeto, así ``import pdf_viewer._censorship_profiles`` y
``import pdf_core.censorship_profiles`` son el mismo módulo. Se borrará al retirar
las versiones Flet y Qt.
"""

import sys

from pdf_core import censorship_profiles as _module

sys.modules[__name__] = _module
