# Módulos de Python de la versión web

Todo el Python de la web está en dos sitios:

- **`app/`**: la aplicación. Contiene los servicios que llama el frontend, la ventana y el arranque (ver [arquitectura.md](arquitectura.md)).
- **`src/pdf_core/`**: la lógica de PDF sin interfaz. Es lo único de `src/` que importa `app/`.

`pdf_core` está dentro de `src/` porque la versión Flet, que sigue en producción, también lo usa, y
`flet build` solo empaqueta `src/`.

## Mapa de `src/pdf_core`

| Módulo | Qué hace | Lo usa en la web |
|---|---|---|
| `document_io.py` | Abrir, serializar y reabrir documentos (conserva el cifrado) | `services/viewer.py` |
| `page_ops.py` | Rotar, insertar, duplicar, mover y extraer páginas; exportar texto e imágenes | `services/viewer.py` |
| `text_layer.py` + `reading_order.py` | Capa de texto en orden de lectura (también con palabras de OCR); escribe el texto de OCR como texto invisible para EmbedPDF | `services/viewer.py`, `services/ocr.py` |
| `annot_transfer.py` | Pasar las anotaciones de la copia del visor (EmbedPDF) al documento abierto, como objetos PDF | `services/viewer.py` |
| `stamps.py` | Sellos predeterminados y conversión de colores | `services/legends.py` |
| `legends.py` | Leyendas guardadas (`~/.extraer_pdfs_legends.json`) | `services/legends.py` |
| `recent_files.py` | Archivos recientes (`~/.extraer_pdfs_recent.json`) | `services/documents.py`, `services/viewer.py` |
| `security.py` | Detectar cifrado, desbloquear, proteger y leer permisos | `services/security.py`, `services/viewer.py` |
| `redaction.py` | Censura: buscar términos, patrones y palabras de OCR; aplicar las marcas de censura (`apply_marks`) | `services/redact.py`, `services/viewer.py` |
| `censorship_profiles.py` | Perfiles de censura (`~/.extraer_pdfs_profiles.json`) | `services/redact.py` |
| `agent/` (`pdf_agent`, `rag`, `extractor`, `config`) | Agente de IA (Gemini u OpenAI) y su configuración (`~/.extraer_pdfs_config.json`). Dependencias opcionales: `config` funciona sin ellas | `services/ai.py` |
| `extractor/` (`engine`, `model`) | Extracción por palabras clave o rango, puntuación y OCR por página | `services/extract/` |
| `merge/` (`engine`, `model`) | Combinación de PDFs, selección de páginas y rangos | `services/merge.py` |
| `ocr/` (`processor`, `paddle`) | OCR y detección de orientación. `paddle.py` ejecuta los modelos de PaddleOCR (PP-OCRv6 *small* y PP-LCNet, en `src/assets/ocr_models`) con onnxruntime y NumPy, sin OpenCV | `services/extract/`, `services/ocr.py` |
| `page_ranges.py` | Rangos de páginas `"1-3, 5"` y páginas elegidas en imprimir u OCR por lotes | `extractor`, `merge`, `services/viewer.py`, `services/ocr.py` |
| `launch_args.py` | PDF recibidos al lanzar la app («Abrir con», `EXTRAR_PDF_PATH`) | `app/main.py` |
| `text_utils.py` | Comparar texto sin tildes | `extractor` |

## Reglas

1. **`app/` solo importa `pdf_core` de `src/`.**
   - Si la web necesita lógica que aún está en un módulo de Flet, primero se mueve a `pdf_core` y se deja un módulo de compatibilidad en la ruta antigua (ver abajo).
2. **`pdf_core` no importa interfaces.**
   - Nada de Flet, Qt, pywebview ni `app`.
   - Nada de módulos de Flet de `src/`.
   - Se puede probar sin ventana.
3. **Los imports son absolutos desde `pdf_core`** (`from pdf_core.merge import engine`), salvo dentro de un mismo subpaquete (`from .model import …`).

`tests/test_web_architecture.py` comprueba las reglas 1 y 2 en cada archivo.

## Compatibilidad con Flet y Qt

Las rutas antiguas siguen funcionando. `src/recent_files.py`, `src/pdf_merge/engine.py`,
`src/pdf_viewer/_text_legends.py`, etc. son módulos de una línea que registran el módulo de `pdf_core`
con su nombre antiguo:

```python
from pdf_core import recent_files as _module
sys.modules[__name__] = _module
```

Así `import recent_files` e `import pdf_core.recent_files` devuelven **el mismo objeto**. El estado
global (como el gestor de leyendas) y los parches de los tests se comparten, y no se cargan dos
copias del modelo de OCR.

| Ruta antigua | Ruta nueva |
|---|---|
| `text_utils`, `page_ranges`, `recent_files` | `pdf_core.text_utils`, `pdf_core.page_ranges`, `pdf_core.recent_files` |
| `pdf_security.security` | `pdf_core.security` |
| `pdf_viewer._text_legends` | `pdf_core.legends` |
| `pdf_viewer._censorship_profiles` | `pdf_core.censorship_profiles` |
| `agent.config`, `agent.pdf_agent`, `agent.rag`, `agent.extractor` | `pdf_core.agent.*` |
| `src_qt.core.launch_args` | `pdf_core.launch_args` |
| `pdf_viewer.ocr.processor` | `pdf_core.ocr.processor` |
| `pdf_extractor.engine`, `pdf_extractor.model` | `pdf_core.extractor.engine`, `pdf_core.extractor.model` |
| `pdf_merge.engine`, `pdf_merge.model` | `pdf_core.merge.engine`, `pdf_core.merge.model` |

## Plan de retirada

### Qt, al completar [paridad.md](paridad.md)

Qt se quita de la rama. Su historia queda en git.

1. Borrar:
   - `src_qt/`;
   - `docs/qt/`;
   - los tests de Qt (`tests/test_qt_*.py` y lo que importe `src_qt`).
2. En `pyproject.toml`:
   - quitar `pyside6` y `pytest-qt`;
   - quitar `src_qt/**/*.py` de la lista de ruff.
3. Dejar de comparar `app/ui/src/styles/tokens.css` con `src_qt/core/theme.py`. A partir de ahí, `tokens.css` es la fuente de los colores.
4. Sustituir las menciones a Qt en `docs/web/` («equivale a … en Qt») por la descripción de la propia web.

### Flet, cuando ya no haga falta por compatibilidad

1. Borrar la interfaz Flet de `src/` y los módulos de compatibilidad, y dejar solo `src/pdf_core/` y `src/assets/`.
2. Quitar `flet` de las dependencias y la sección `[tool.flet]`.
3. Quitar `docs/flet/` y los tests de Flet.
4. Opcional: mover `pdf_core` fuera de `src/` (por ejemplo, a la raíz del proyecto) y actualizar las rutas en `app/__init__.py` y `pyproject.toml`.
