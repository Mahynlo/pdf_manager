# Arquitectura de la versión web (pywebview)

Nueva interfaz de PDF Manager: **frontend en Svelte** (HTML/CSS/JS compilado con Vite) y
**backend en Python**, unidos por pywebview (WebView2 de Edge en Windows, que ya viene con el sistema).
La versión Qt (`src_qt/`) es la referencia de funciones y aspecto hasta completar la migración.

```
uv run python -m app.main            # arrancar (compila la interfaz si cambió)
uv run python -m app.main --dev      # con recarga al guardar (arranca y cierra «pnpm dev»)
uv run python -m app.main --debug    # con herramientas de desarrollo (F12)
```

Hacen falta Node.js y pnpm para compilar la interfaz; ver [svelte.md](svelte.md).

## Estructura

```
app/
  main.py                 arranque: instancia única, crea la ventana, registra servicios;
                          abre la interfaz (compilada, o con --dev / --dev-server URL)
  ui_dev.py               compila la interfaz si cambió y, con --dev, arranca y detiene «pnpm dev»
  byte_server.py          servidor local de un solo uso para datos grandes (Host.share_bytes)
  single_instance.py      una sola ventana: las nuevas instancias le pasan sus PDF («Abrir con»)
  webview_cache.py        descarta la caché de WebView2 cuando cambia el frontend
  host.py                 WebviewHost: diálogos, abrir carpetas y enlaces, eventos → JS (lo único que usa pywebview)
  backend/                Python sin interfaz: no importa Qt ni pywebview
    rpc.py                @exposed, Registry, UserError, Api (punto de entrada único)
    host.py               protocolo Host que usan los servicios
    settings.py           preferencias en ~/.pdf_manager/settings.json
    imaging.py            páginas como data URL para <img>
    services/             un servicio por área + build_registry():
                          app (preferencias), documents (pedir abrir un PDF, recientes), merge,
                          security, extract/ (servicio + trabajo en segundo plano con eventos extract:*),
                          help (manuales Markdown → HTML seguro), viewer (PDFs abiertos en el visor),
                          ocr (OCR y orientación sobre los documentos del visor), redact (censura),
                          ai (asistente IA),
                          legends (sellos y leyendas)
  ui/                     la interfaz, en Svelte (compila a ui/dist con pnpm build): ver svelte.md
    src/main.js           arranque: estilos, tema guardado y App
    src/styles/           tokens.css (colores del tema, mismos valores que src_qt/core/theme.py),
                          base.css, components.css y uno por área
    src/assets/icons.json trazos de los iconos (también los usa la versión Qt)
    src/App.svelte        ventana: cabecera con pestañas, vistas, barra de estado, avisos y menú
    src/lib/              api.js (puente con Python), ui.js (avisos, barra de estado y diálogos),
                          menu.svelte.js (menús emergentes), theme.svelte.js, thumbs.js
                          (miniaturas bajo demanda), Icon.svelte, components/ (diálogos y controles)
    src/shell/            shell.svelte.js (pestañas), tools.js (registro de herramientas), Inicio
                          y dropzone.js (arrastrar PDFs a la ventana)
    src/tools/<herramienta>/   un componente por herramienta y sus piezas
    src/tools/viewer/     visor: Viewer.svelte (compone), barras, miniaturas, índice y pestañas del
                          panel lateral (OCR, censura, IA, búsqueda) y sus diálogos; el lienzo es
                          código imperativo: canvas.js (lienzo sobre EmbedPDF, ver embedpdf.md),
                          embed.js y EmbedRoot.svelte (registro de EmbedPDF), PdfPages.svelte y
                          PdfPage.svelte (páginas),
                          layout.js (modos de vista),
                          text.js (selección de texto con EmbedPDF), annotations.js (anotaciones con EmbedPDF),
                          editing.js (barra de propiedades), operations.js (menú ⋮)
```

La lógica de PDF está en `src/pdf_core/` (motores de combinar, extraer, seguridad, OCR, capa de texto,
anotaciones…): es lo único de `src/` que importa `app/`. Mapa y reglas en [modulos-python.md](modulos-python.md).

## Cómo se comunican

- **JS → Python:** `await call('merge.toggle', id, pagina)`. Solo se pueden llamar métodos
  marcados con `@exposed` de un servicio registrado. Errores previstos: `raise UserError("mensaje")`
  → la promesa se rechaza con ese mensaje (se muestra como aviso).
- **Python → JS:** `host.emit('merge:progress', {...})` → `on('merge:progress', fn)` en JS.
- **El estado vive en el backend.** Cada acción devuelve el estado completo y la vista se repinta
  a partir de él; el frontend no duplica lógica (rangos, selección, permisos…).
- pywebview ejecuta cada llamada en su propio hilo: los servicios protegen su estado con un candado
  (`fitz.Document` no admite acceso concurrente).

## Reglas

- **Nada de HTML con datos**: Svelte inserta los textos como texto. `{@html}` solo para el HTML que
  el backend ya genera seguro (manuales y respuestas de la IA). El código imperativo del lienzo crea
  sus elementos con `h()` (`lib/dom.js`).
- **Colores solo desde `tokens.css`** (`var(--accent)`…). El tema cambia con `data-theme` en `<html>`.
  Si cambia una paleta de Qt, hay que regenerar `tokens.css` (un test compara ambos).
- **Iconos**: `<Icon name="nombre" />` (o `ic('nombre')` en el código del lienzo). Usan
  `currentColor`, así que siguen el tema solos. Un icono nuevo se añade a `app/ui/src/assets/icons.json`.
- **Listas con clave**: `{#each lista as item (item.id)}`, así Svelte reutiliza los elementos al
  repintar y no se pierde el desplazamiento.
- **Abrir PDFs**: desde el backend, `DocumentService.open(ruta, contraseña=None)` emite
  `document:open` y el shell abre la pestaña; desde el frontend, `shell.openDocument(ruta)`. En ambos
  casos el PDF lo carga `viewer.open`, que pide la contraseña si falta y añade el archivo a recientes.
- **Aspecto igual a la versión Qt**: mismos textos, colores y disposición. Los componentes de
  `lib/components/` equivalen a los de Qt (`PasswordField` = PasswordLineEdit, `Fieldset` = QGroupBox,
  `Banner` = StatusBanner, `SubTabs` = QTabWidget, `openMenu` = QMenu).
- **Trabajos largos en un hilo del backend** (ver `services/extract/`): el servicio valida y lanza el
  trabajo; este avisa con eventos (`host.emit`) y el servicio envía el evento final cuando ya lo
  liberó. Si el trabajo necesita algo del usuario (una contraseña), emite un evento y espera la
  respuesta con un `threading.Event`. Una herramienta con trabajo en curso implementa `canClose()`.
- **Imágenes bajo demanda**: miniaturas solo para lo visible (`IntersectionObserver`), por lotes,
  en JPEG y con caché acotada (`lib/thumbs.js`). Las páginas del visor las dibuja
  EmbedPDF en el navegador, solo las que están a la vista y en mosaico a la resolución del zoom, a
  partir de los bytes del documento abierto en Python (`viewer.document_url`, ver [embedpdf.md](embedpdf.md)).
- **Datos grandes hacia el frontend**: el puente de pywebview pasa los valores como texto JSON. Para
  datos grandes (un PDF entero), `host.share_bytes(datos, tipo)` da una URL de un solo uso en
  127.0.0.1 (`app/byte_server.py`) y el frontend los descarga en binario con `fetch`.
- **Atajos de una pestaña**: su componente exporta `onKey(ev)`; el shell se lo pasa solo cuando
  es la pestaña activa y no hay un diálogo abierto.
- **Cambios en el documento del visor**: cada operación de `viewer.*` devuelve la información
  completa del documento (tamaños y claves de página, índice, `modified`) y el visor se repinta con
  ella. La clave de página (`xref:rotación`) identifica su imagen: cuando cambian, el lienzo vuelve a
  cargar el documento en EmbedPDF.
- **Texto del visor**:
  - la selección es del complemento Selection de EmbedPDF, con el texto que PDFium lee del
    documento. El texto reconocido por OCR va en el documento que recibe EmbedPDF como texto
    invisible (`viewer.document_url`), así que se selecciona igual; tras un OCR el lienzo recarga
    el documento (`canvas.reload`);
  - la búsqueda también es de EmbedPDF (complemento Search, en `SearchPanel.svelte`), sobre ese
    mismo documento;
  - el asistente IA y el panel de OCR leen la capa de texto del backend (`pdf_core/text_layer.py`,
    `viewer.text_of`): el texto en orden de lectura, con el nativo y el de OCR;
  - lo que se dibuja sobre una página (selección, coincidencias) va en su capa de marcas
    (`canvas.addMark`), en puntos de la página tal como se ve y medido en porcentaje.
- **Anotaciones**: las dibuja y edita EmbedPDF (complementos Annotation y History) en su copia del
  documento, con deshacer y rehacer en el navegador. Antes de lo que necesita el documento al día en
  Python (guardar, exportar una página, cambiar páginas, censurar, OCR), el visor sube su
  copia (`viewer.sync_annotations`, por el servidor local de datos) y Python toma de ella solo las
  anotaciones (`pdf_core/annot_transfer.py`); el contenido, el cifrado, los formularios y los
  enlaces siguen siendo los suyos. Ver [embedpdf.md](embedpdf.md).
- **Ratón en el lienzo**: cada página va en un `PagePointerProvider` de EmbedPDF, que pasa el ratón
  a la selección de texto (solo con las herramientas de texto, por los modos del gestor de
  interacción) y a las anotaciones (seleccionar, mover, dibujar con su herramienta activa). Los
  eventos siguen subiendo al lienzo, donde escuchan la mano y el recorte de OCR.
- **Caché del navegador**: el servidor de pywebview sirve el frontend sin `Cache-Control`, así que
  WebView2 podría seguir usando JS/CSS de una versión anterior aunque se reinicie la app. Al
  arrancar, `app/webview_cache.py` compara una huella de la interfaz (`app/ui/dist`) con la del arranque
  anterior y, si cambió, borra la caché HTTP de WebView2 (no las preferencias).
- **OCR**: el servicio `ocr` rasteriza la página con el candado del visor y hace la inferencia sin él
  (el lienzo sigue respondiendo); una inferencia a la vez y el modelo se libera tras 12 s sin uso. Las
  palabras se guardan en el documento abierto por clave de página (`ViewerService.set_ocr_words`) y
  entran en su capa de texto: selección, búsqueda y exportar texto las ven sin cambios. Los lotes los
  recorre el frontend página a página (`ocr.page`), así se puede cancelar entre una y otra.
- **Censura**: lo que se censura son las marcas de EmbedPDF (anotaciones `Redact`, ver
  `redaction.js`), que se revisan en la página. El servicio `redact` busca dónde aparece cada término
  (`find`) y guarda las opciones, el color y el perfil activo en el propio documento abierto
  (`_OpenDocument.extras`). Al aplicar, las marcas llegan con las anotaciones y
  `ViewerService.apply_redaction_marks` las aplica: borra el contenido de debajo (también las
  palabras de OCR) y sube la revisión de esas páginas, así su clave cambia y el lienzo no reutiliza
  la imagen anterior. Un documento censurado (`redacted`) solo se guarda como copia.
- **Imprimir**: sin Qt ni pywin32, con la impresión del navegador. El diálogo propio elige las páginas
  (`viewer.print_selection`) y las opciones; PDFium dibuja esas páginas con sus anotaciones a 150 ppp
  en el navegador (`canvas.pageImages`), se colocan en `#print-root` (lo único visible con `@media print`, una hoja
  por página con `page: pm-portrait | pm-landscape`) y `window.print()` abre el diálogo del sistema.
  Las medidas `vw`/`vh` de impresión son las de la hoja vertical por defecto: las hojas horizontales
  las intercambian. La capa se borra con `afterprint`.
- **Asistente IA**: el servicio `ai` copia lo necesario del documento con el candado del visor y
  consulta sin él (las respuestas tardan segundos). Usa `pdf_core.agent.PDFAgent` si sus dependencias
  están instaladas y hay clave; si no, responde en modo básico. Las respuestas llegan también como
  HTML de Markdown sin HTML crudo, imágenes ni enlaces, que el frontend inserta tal cual.
- **Arrastrar PDFs y «Abrir con»**: el navegador no da la ruta de un archivo soltado; `WebviewHost`
  escucha el `drop` desde Python (pywebview añade `pywebviewFullPath`) y abre los PDF con
  `DocumentService.open`. `shell/dropzone.js` solo evita que WebView2 navegue al archivo y muestra el aviso.
  Los PDF recibidos al arrancar (o de otra instancia) se abren cuando el frontend llama a `app.ready`.
- **Tareas largas con progreso**: `progressDialog()` de `lib/ui.js` (barra y «Cancelar»).
- **Cerrar con cambios sin guardar**: el componente de la pestaña lo pregunta en `canClose()`. Al cerrar la ventana,
  `WebviewHost` cancela el cierre si hay documentos modificados y emite `app:quit-requested`; el
  shell pregunta y, si se acepta, llama a `app.quit`.

## Añadir una herramienta

1. Backend: `app/backend/services/<nombre>.py` con métodos `@exposed` que usen la lógica de `pdf_core`
   (si aún está en un módulo de Flet, moverla antes a `pdf_core`, ver [modulos-python.md](modulos-python.md));
   registrarlo en `services/__init__.py`.
2. Frontend: `app/ui/src/tools/<nombre>/<Nombre>.svelte`, que recibe la entrada del registro como
   prop `tool` y libera lo que use con `onDestroy`. Los estilos nuevos, en su bloque `<style>`.
3. Añadir su entrada (con `load: () => import(...)`) en `app/ui/src/shell/tools.js`.
4. Pruebas del servicio en `tests/test_app_backend.py` con `FakeHost`. Los tests también verifican
   que cada `call('servicio.metodo')` y cada icono usados en el frontend existen.

El estado de cada función está en [paridad.md](paridad.md).
