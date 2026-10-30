# Versión Flet

Versión **descartada**: la 0.1.28 fue la última (instalador generado con `build.ps1`) y está
respaldada en la rama `Flet`. Desde la 0.1.29-web solo se publica la versión web. El código se
mantiene por compatibilidad y luego se retirará (ver el plan en
[../web/modulos-python.md](../web/modulos-python.md#plan-de-retirada)).

```
uv run flet run          # arrancar (código en src/, entrada src/main.py)
.\build.ps1              # exe + launcher de «Abrir con» + instalador Inno Setup
```

## Documentos

| Documento | Contenido |
|---|---|
| [visor-pdf.md](visor-pdf.md) | Visor: renderizado, zoom, anotaciones, selección, OCR, censura, búsqueda |
| [cierre-y-guardado.md](cierre-y-guardado.md) | Detección de cambios y protección de datos al cerrar |
| [correccion-orientacion.md](correccion-orientacion.md) | Detección y corrección de la orientación de páginas |
| [combinar-pdf.md](combinar-pdf.md) | Herramienta Combinar |
| [extraer-pdf.md](extraer-pdf.md) | Herramienta Extraer |
| [seguridad-pdf.md](seguridad-pdf.md) | Herramienta Seguridad |
| [abrir-con-windows.md](abrir-con-windows.md) | «Abrir con», instancia única e instalador en Windows |
| [ejecucion_aplicacion_dev.md](ejecucion_aplicacion_dev.md) | Ejecutar y empaquetar con Flet |

## Lógica compartida con la web

La lógica sin interfaz que usa la web se movió a `src/pdf_core/`:
- motores de Combinar y Extraer;
- seguridad;
- OCR;
- leyendas y perfiles de censura;
- recientes;
- rangos de páginas.

La versión Flet la sigue importando por las rutas de siempre (`pdf_merge.engine`,
`pdf_viewer.ocr.processor`, `recent_files`…), que ahora son alias del módulo de `pdf_core`. Cuando un
documento de esta carpeta cita `engine.py`, `model.py`, `security.py` o `processor.py`, el código está
en `src/pdf_core/`.
