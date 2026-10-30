"""Lógica de PDF sin interfaz: la usa la versión web (``app/``).

Aquí va todo el Python que necesita ``app/backend``; ``app/`` no importa nada más
de ``src/``. Ningún módulo de este paquete importa Flet, Qt ni pywebview.

Las versiones Flet y Qt lo usan a través de módulos de compatibilidad con las
rutas antiguas (``recent_files``, ``pdf_merge.engine``…), que se borrarán al
retirar esas versiones. Ver ``docs/web/modulos-python.md``.
"""
