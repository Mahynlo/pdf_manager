# Módulos de Python de la versión web

Todo el Python de la web está en dos sitios:

- **`app/`**: la aplicación. Contiene los servicios que llama el frontend, la ventana y el arranque (ver [arquitectura.md](arquitectura.md)).
- **`src/pdf_core/`**: la lógica de PDF sin interfaz. Es lo único de `src/` que importa `app/`.

`pdf_core` sigue en `src/` por historia (era la carpeta de la versión Flet): se podría mover a la raíz
actualizando las rutas de `app/__init__.py` y `pyproject.toml`.

## Motor de PDF

Todo usa **PDFium** (licencia Apache/BSD): `pypdfium2` en Python y EmbedPDF, su versión en WebAssembly,
en la ventana. Antes el backend usaba PyMuPDF, que es AGPL.

- `pdf_core/pdf.py` es la **única puerta** al motor en Python. PDFium no admite hilos, ni siquiera
  con documentos distintos: todo pasa por el candado `pdf.LOCK`, y por eso ningún otro módulo debe
  importar `pypdfium2` (lo comprueba `tests/test_web_architecture.py`).
- Lo que el PDFium normal no sabe hacer lo hace el de EmbedPDF, que tiene funciones propias: los
  servicios lo piden con `Host.run_engine` (ver [embedpdf.md](embedpdf.md), «Un solo motor»).

## Mapa de `src/pdf_core`

| Módulo | Qué hace | Lo usa en la web |
|---|---|---|
| `pdf.py` | Capa sobre PDFium: documentos, páginas, texto, imágenes. Coordenadas (`Rect`, de página y de vista) | Todos los que tocan un PDF |
| `page_ops.py` | Rotar, insertar, duplicar, mover y extraer páginas; exportar texto e imágenes | `services/viewer.py` |
| `text_layer.py` + `reading_order.py` | Capa de texto en orden de lectura (también con palabras de OCR; el texto invisible para EmbedPDF lo escribe el visor) | `services/viewer.py`, `services/ocr.py` |
| `stamps.py` | Sellos predeterminados y conversión de colores | `services/legends.py` |
| `legends.py` | Leyendas guardadas (`~/.extraer_pdfs_legends.json`) | `services/legends.py` |
| `recent_files.py` | Archivos recientes (`~/.extraer_pdfs_recent.json`) | `services/documents.py`, `services/viewer.py` |
| `security.py` | Detectar cifrado, desbloquear y leer permisos; máscara de permisos para cifrar | `services/security.py`, `services/viewer.py` |
| `redaction.py` | Censura: buscar términos, patrones y palabras de OCR | `services/redact.py` |
| `censorship_profiles.py` | Perfiles de censura (`~/.extraer_pdfs_profiles.json`) | `services/redact.py` |
| `agent/` (`pdf_agent`, `rag`, `extractor`, `config`) | Agente de IA (Gemini u OpenAI) y su configuración (`~/.extraer_pdfs_config.json`). Dependencias opcionales: `config` funciona sin ellas | `services/ai.py` |
| `extractor/` (`engine`, `model`) | Extracción por palabras clave o rango, puntuación y OCR por página | `services/extract/` |
| `merge/` (`engine`, `model`) | Combinación de PDFs, selección de páginas y rangos | `services/merge.py` |
| `ocr/` (`processor`, `paddle`) | OCR y detección de orientación. `paddle.py` ejecuta los modelos de PaddleOCR (PP-OCRv6 *small* y PP-LCNet, en `src/assets/ocr_models`) con onnxruntime y NumPy, sin OpenCV | `services/extract/`, `services/ocr.py` |
| `page_ranges.py` | Rangos de páginas `"1-3, 5"` y páginas elegidas en el OCR por lotes | `extractor`, `merge`, `services/ocr.py` |
| `launch_args.py` | PDF recibidos al lanzar la app («Abrir con», `EXTRAR_PDF_PATH`) | `app/main.py` |
| `text_utils.py` | Comparar texto sin tildes | `extractor` |

## Reglas

1. **`app/` solo importa `pdf_core` de `src/`.**
2. **`pdf_core` no importa interfaces.**
   - Nada de pywebview ni `app`.
   - Se puede probar sin ventana.
3. **Los imports son absolutos desde `pdf_core`** (`from pdf_core.merge import engine`), salvo dentro de un mismo subpaquete (`from .model import …`).

`tests/test_web_architecture.py` comprueba estas reglas en cada archivo, y que nada use MuPDF.

## Pruebas

`tests/pdfkit.py` crea los PDF de prueba con PDFium. Lo que hace el motor de EmbedPDF (cifrar, censurar,
marcadores) se prueba con el motor real: `tests/engine_task.mjs` lo ejecuta en Node con el mismo código
que la ventana (`app/ui/src/lib/engine-tasks.ts`). Hace falta Node y `pnpm install` en `app/ui`.
