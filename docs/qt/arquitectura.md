# Arquitectura del cliente PySide6

Cómo está organizado `src_qt/`, qué reglas sigue y dónde añadir cada cosa.

> Qt es la referencia para migrar a la versión web y se retirará al terminar ([README](README.md)).
> La lógica sin interfaz está ahora en `src/pdf_core/` ([mapa](../web/modulos-python.md)); las rutas
> antiguas que usa `src_qt` (`pdf_merge.engine`, `page_ranges`…) son alias de esos módulos.

## 1. Capas

```
src/        Lógica sin interfaz en src/pdf_core (compartida con Flet y la web)
src_qt/
  core/     Infraestructura Qt sin pantallas: tema, ajustes, rutas, IPC, escritorio
  ui/
    shell/      Ventana principal, barra de pestañas y registro de herramientas
    tools/      Una carpeta por herramienta (home, extractor, merge, security, settings, help)
    viewer/     Visor PDF (lienzo, paneles laterales, diálogos del visor)
    dialogs/    Diálogos reutilizables (contraseña, cambios sin guardar)
    widgets/    Widgets reutilizables (separadores, campo de contraseña, etiqueta de error)
    rendering.py  Conversión fitz → QImage/QPixmap
```

Las dependencias van en una sola dirección: `ui` → `core` → `src`.
Las herramientas no se importan entre sí; si una necesita a otra (por ejemplo
"Ir a Seguridad"), emite una señal y el registro la conecta.

## 2. Reglas

| Regla | Motivo |
|---|---|
| La lógica de PDFs (abrir, buscar, combinar, extraer, OCR) vive en `src/` | La comparten Flet y Qt; un solo sitio que corregir y probar |
| `src_qt` nunca importa Flet | Importar `pdf_viewer`, `pdf_extractor`… es seguro: sus `__init__` cargan la UI Flet de forma diferida |
| Nada de colores fijos en `setStyleSheet`: texto con `role` (`Role.X`), botones con `variant` (`Variant.PRIMARY`, `SUCCESS`, `DANGER`, `GHOST`, `ICON`, `TOGGLE`, `CHIP`, `COMPACT`), avisos con `tone` (`StatusBanner`) | El tema claro/oscuro se aplica solo (ver `core/theme.py`); solo se permiten colores de *contenido* (muestras de color, identidad de una herramienta) |
| Iconos de interfaz: `ui/icons.py` — `set_button_icon(btn, nombre)`, `icon_label(nombre)`, `set_tab_icons(tabs, [...])`, `set_action_icon(acción, nombre)`; añadir uno = sumar su trazo SVG a `_PATHS` | Nítidos en HiDPI y se recolorean solos al cambiar de tema (`retheme_icons`); nada de emojis/caracteres como iconos de botones, pestañas o menús. Un test comprueba que todo nombre usado exista |
| Cabecera de cada herramienta: `ToolHeader(icono, título, subtítulo, accent)` | Mismo aspecto en todas las pestañas |
| Cambiar `role`/`tone` de un widget ya visible: `set_style_property` | Qt no recalcula solo los selectores por propiedad |
| Botones pequeños de tamaño fijo: siempre con `variant` (`ICON`, `TOGGLE`) | El relleno general del botón deja sin espacio el texto y se ven vacíos |
| Separadores, campos de contraseña y errores: `ui/widgets` | Mismo aspecto y comportamiento en toda la app |
| Pedir contraseña: `ask_pdf_password` (`ui/dialogs`) | Un solo diálogo, con validación y botón "Ir a Seguridad" opcionales |
| Abrir carpetas, revelar archivos o buscar en la web: `core/desktop.py` | Un solo sitio; los fallos se registran en el log |
| Rangos de páginas ("1-3, 5"): `page_ranges.parse_pages` | Mismo criterio en extraer, combinar, imprimir y OCR |
| No silenciar excepciones: `log.exception(...)` o capturar el error concreto | El log de diagnóstico (Ajustes → Registro) sirve para depurar |
| Métodos con `_` son internos: no se llaman desde otro módulo | Si otro módulo lo necesita, se le da un nombre público |
| Cachés de imágenes o datos por página: `core/lru.LRUCache` (por número o por bytes), nunca un `dict` sin límite | La memoria no crece con el tamaño del PDF ni con el zoom |
| Rasterizar solo lo visible y soltar lo lejano (lienzo y miniaturas) | Un PDF de 1000 páginas gasta lo mismo que uno de 10 |

## 3. Añadir una herramienta

1. Crear `src_qt/ui/tools/<nombre>/` con `tab.py` (un `QWidget`) y un `__init__.py`
   que exporte la clase. Si tiene trabajo en segundo plano, ponerlo en `worker.py`
   y la lógica en `src/`.
2. Registrarla en `src_qt/ui/shell/tool_registry.py`:

   ```python
   def _build_mi_tool(ctx: AppContext) -> QWidget:
       from src_qt.ui.tools.mi_tool import MiToolTab
       tab = MiToolTab()
       tab.open_in_viewer_requested.connect(ctx.open_pdf)   # si abre PDFs
       return tab

   TOOLS.append(ToolSpec(
       "mi_tool", "🧩 Mi tool", "🧩  Mi herramienta", _build_mi_tool,
       home_card=HomeCard("Mi herramienta", "Qué hace\nen dos líneas", "🧩", "#6A1B9A"),
   ))
   ```

Con eso aparece en el menú de la marca, en Inicio (si tiene `home_card`) y se
abre como pestaña única. No hay que tocar la ventana principal.

3. Si puede estar ocupada (un hilo en curso), implementar `request_close() -> bool`:
   la ventana lo llama antes de cerrar la pestaña o la aplicación.

## 4. Añadir una función al visor

`PdfViewerWidget` (`viewer/pdf_viewer.py`) se compone de mixins por tema. Cada
función nueva va en el que corresponde:

| Mixin | Para |
|---|---|
| `_toolbar_mixin` | Botones, menús e iconos |
| `_navigation_mixin` | Páginas, zoom, modos de vista, paneles laterales |
| `_page_ops_mixin` | Rotar, insertar, mover o eliminar páginas (volcar anotaciones antes con `_flush_annotations`) |
| `_file_ops_mixin` | Guardar, exportar, imprimir |
| `_search_mixin` | Búsqueda y acciones sobre texto seleccionado |

El lienzo (`viewer/canvas/`) sigue la misma idea: `view.py` (geometría, ratón,
modos), `text_selection.py`, `annotation_editing.py`, `annotation_io.py`
(conversión escena ↔ PDF), `overlays.py`, y un archivo por tipo de anotación en
`items/`.

Los atajos de teclado del visor se definen en `pdf_viewer._setup_shortcuts`; si
se añade uno, actualizar también la lista en `tools/settings/tab.py`.

## 5. Calidad

```powershell
uvx ruff check            # errores, imports, bugs comunes (config en pyproject.toml)
$env:QT_QPA_PLATFORM="offscreen"; uv run pytest
```

Tests relevantes: `test_qt_parity.py` (comportamiento igual a Flet),
`test_qt_architecture.py` (registro y widgets), `test_shared_backend.py`
(módulos compartidos y que Qt no cargue Flet).
