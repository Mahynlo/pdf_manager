# Arquitectura de la versión web (pywebview)

Nueva interfaz de PDF Manager: **frontend en Svelte** (HTML/CSS/JS compilado con Vite) y
**backend en Python**, unidos por pywebview (WebView2 de Edge en Windows, que ya viene con el sistema).

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
  backend/                Python sin interfaz: no importa pywebview
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
                          legends (sellos de texto y leyendas), stamps (sellos propios y firmas)
  ui/                     la interfaz, en Svelte (compila a ui/dist con pnpm build): ver svelte.md
    src/main.ts           arranque: estilos, tema guardado y App
    src/styles/           tokens.css (colores del tema),
                          base.css, components.css y uno por área
    src/assets/icons.json trazos de los iconos
    src/App.svelte        ventana: cabecera con pestañas, vistas, barra de estado, avisos y menú
    src/lib/              api.ts (puente con Python), ui.ts (avisos, barra de estado y diálogos),
                          menu.svelte.ts (menús emergentes), theme.svelte.ts, thumbs.ts
                          (miniaturas bajo demanda), Icon.svelte, components/ (diálogos y controles)
    src/shell/            shell.svelte.ts (pestañas), tools.ts (registro de herramientas), Inicio
                          y dropzone.ts (arrastrar PDFs a la ventana)
    src/tools/<herramienta>/   un componente por herramienta y sus piezas
    src/tools/viewer/     visor: Viewer.svelte (compone) y una carpeta por parte (ver su README.md):
                          canvas/ (lienzo, páginas y selección con EmbedPDF), annotations/,
                          redact/ (censura), ocr/, document/ (guardar, páginas, imprimir),
                          toolbars/ y panels/ (miniaturas, índice, búsqueda, IA)
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
  (además, PDFium no admite hilos: `pdf_core.pdf` lo serializa todo con un candado global).
- **Python → motor de la ventana:** `host.run_engine('redact', pdf, args)` para lo que solo sabe
  hacer el PDFium de EmbedPDF: emite `engine:task`, la ventana hace la tarea (`lib/engine.ts`) y sube
  el resultado. Ver [embedpdf.md](embedpdf.md), «Un solo motor».

## Reglas

- **Nada de HTML con datos**: Svelte inserta los textos como texto. `{@html}` solo para el HTML que
  el backend ya genera seguro (manuales y respuestas de la IA). El código imperativo del lienzo crea
  sus elementos con `h()` (`lib/dom.ts`).
- **Colores solo desde `tokens.css`** (`var(--accent)`…). El tema cambia con `data-theme` en `<html>`.
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
  en JPEG y con caché acotada (`lib/thumbs.ts`). Las páginas del visor las dibuja
  EmbedPDF en el navegador, solo las que están a la vista y en mosaico a la resolución del zoom, a
  partir del documento que tiene abierto (el archivo lo da `viewer.document_url`, ver [embedpdf.md](embedpdf.md)).
- **Datos grandes hacia el frontend**: el puente de pywebview pasa los valores como texto JSON. Para
  datos grandes (un PDF entero), `host.share_bytes(datos, tipo)` da una URL de un solo uso en
  127.0.0.1 (`app/byte_server.py`) y el frontend los descarga en binario con `fetch`. El visor abre su
  archivo con `host.file_url(ruta)`, que en el navegador es una URL del archivo que tiene la ventana.
- **Archivos del visor**: el visor lee y escribe sus documentos con el `Host` (`read_file`,
  `write_file`, `file_size`, `file_url`), nunca con rutas; las herramientas abren rutas con `pdf_core`.
  En el navegador así el visor no guarda copia en Python (ver [navegador.md](navegador.md)).
- **Atajos de una pestaña**: su componente exporta `onKey(ev)`; el shell se lo pasa solo cuando
  es la pestaña activa y no hay un diálogo abierto.
- **Cambios en el documento del visor**: cada operación de `viewer.*` devuelve la información
  completa del documento (tamaños y claves de página, índice, `modified`) y el visor se repinta con
  ella. La clave de página (`xref:rotación`) identifica su imagen: cuando cambian, el lienzo vuelve a
  cargar el documento en EmbedPDF.
- **Texto del visor**:
  - la selección es del complemento Selection de EmbedPDF, con el texto que PDFium lee del
    documento. El texto reconocido por OCR lo escribe el visor en su documento como texto invisible
    (`canvas.writeOcrText`), así que se selecciona igual, sin volver a abrir el documento;
  - la búsqueda también es de EmbedPDF (complemento Search, en `SearchPanel.svelte`), sobre ese
    mismo documento;
  - el asistente IA y el panel de OCR leen la capa de texto del backend (`pdf_core/text_layer.py`,
    `viewer.text_of`): el texto en orden de lectura, con el nativo y el de OCR;
  - lo que se dibuja sobre una página (selección, coincidencias) va en su capa de marcas
    (`canvas.addMark`), en puntos de la página tal como se ve y medido en porcentaje.
- **Anotaciones, páginas y censura**: las hace EmbedPDF (complementos Annotation y History, y el
  motor de la app) en su documento, con deshacer y rehacer en el navegador. Python no tiene el
  documento: recibe la clave y el texto de cada página que le falta (`document/text.ts`,
  `viewer.set_pages` y `viewer.add_texts`, por el servidor local de datos) y, al guardar o extraer
  una página, la copia que saca el motor sin el texto del OCR (`document/copy.ts`), que escribe tal
  cual. Ver [embedpdf.md](embedpdf.md), etapa 4.
- **Ratón en el lienzo**: cada página va en un `PagePointerProvider` de EmbedPDF, que pasa el ratón
  a la selección de texto (solo con las herramientas de texto, por los modos del gestor de
  interacción) y a las anotaciones (seleccionar, mover, dibujar con su herramienta activa). Los
  eventos siguen subiendo al lienzo, donde escuchan la mano y el recorte de OCR.
- **Caché del navegador**: el servidor de pywebview sirve el frontend sin `Cache-Control`, así que
  WebView2 podría seguir usando JS/CSS de una versión anterior aunque se reinicie la app. Al
  arrancar, `app/webview_cache.py` compara una huella de la interfaz (`app/ui/dist`) con la del arranque
  anterior y, si cambió, borra la caché HTTP de WebView2 (no las preferencias).
- **OCR**: el visor dibuja con su motor lo que hay que reconocer y lo sube (`ocr/recognize.ts`); el
  servicio `ocr` solo hace la inferencia, sin el candado del visor (el lienzo sigue respondiendo). Una
  inferencia a la vez y el modelo se libera tras 12 s sin uso. Las palabras se guardan en el
  documento abierto por clave de página (`ViewerService.set_ocr_words`), entran en su capa de texto
  (IA, exportar texto) y el visor las escribe en su documento: selección y búsqueda las ven sin
  cambios. Los lotes los recorre el frontend página a página (`ocr.page`), así se puede cancelar
  entre una y otra. La orientación la dice el texto de la página o, en un escaneo, el clasificador
  de Python con dos imágenes de ella. Ver [embedpdf.md](embedpdf.md), etapa 3.
- **Censura**: lo que se censura son las marcas de EmbedPDF (anotaciones `Redact`, ver
  `redaction.ts`), que se revisan en la página. El servicio `redact` busca dónde aparece cada término
  (`find`) y guarda las opciones, el color y el perfil activo en el propio documento abierto
  (`_OpenDocument.extras`). Al aplicar, el motor del visor borra el contenido de debajo en su
  documento (`redact/apply.ts`) y sube la revisión de esas páginas, así su clave cambia y nada
  reutiliza su imagen ni su texto anteriores; `redact.apply` le dice a Python qué páginas, y el
  visor le da su texto nuevo y las palabras de OCR que quedan. Un documento censurado (`redacted`)
  solo se guarda como copia.
- **Imprimir**: el diálogo de impresión de WebView2 con el PDF y sus anotaciones
  en un iframe oculto (`document/print.ts`). Ver embedpdf.md, «Imprimir».
- **Asistente IA**: el servicio `ai` copia lo necesario del documento con el candado del visor y
  consulta sin él (las respuestas tardan segundos). Usa `pdf_core.agent.PDFAgent` si sus dependencias
  están instaladas y hay clave; si no, responde en modo básico. Las respuestas llegan también como
  HTML de Markdown sin HTML crudo, imágenes ni enlaces, que el frontend inserta tal cual.
- **Arrastrar PDFs y «Abrir con»**: el navegador no da la ruta de un archivo soltado; `WebviewHost`
  escucha el `drop` desde Python (pywebview añade `pywebviewFullPath`) y abre los PDF con
  `DocumentService.open`. `shell/dropzone.ts` solo evita que WebView2 navegue al archivo y muestra el aviso.
  Los PDF recibidos al arrancar (o de otra instancia) se abren cuando el frontend llama a `app.ready`.
- **Tareas largas con progreso**: `progressDialog()` de `lib/ui.ts` (barra y «Cancelar»).
- **Cerrar con cambios sin guardar**: el componente de la pestaña lo pregunta en `canClose()`. Al cerrar la ventana,
  `WebviewHost` cancela el cierre si hay documentos modificados y emite `app:quit-requested`; el
  shell pregunta y, si se acepta, llama a `app.quit`.

## Añadir una herramienta

1. Backend: `app/backend/services/<nombre>.py` con métodos `@exposed` que usen la lógica de `pdf_core`
   (ver [modulos-python.md](modulos-python.md));
   registrarlo en `services/__init__.py`.
2. Frontend: `app/ui/src/tools/<nombre>/<Nombre>.svelte`, que recibe la entrada del registro como
   prop `tool` y libera lo que use con `onDestroy`. Los estilos nuevos, en su bloque `<style>`.
3. Añadir su entrada (con `load: () => import(...)`) en `app/ui/src/shell/tools.ts`.
4. Pruebas del servicio en `tests/test_app_backend.py` con `FakeHost`. Los tests también verifican
   que cada `call('servicio.metodo')` y cada icono usados en el frontend existen.

El estado de cada función está en [paridad.md](paridad.md).
