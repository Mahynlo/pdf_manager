# Changelog

## [0.1.18] - 2026-06-09

### Added
- **Rehacer anotaciones (Ctrl+Y / Ctrl+Shift+Z)**: complementa a Deshacer. Al deshacer una anotación, `AnnotationManager` guarda una instantánea de su geometría y estilo (`_snapshot_annot`) en una pila de rehacer; rehacer la recrea con `_recreate_annot`. La pila se invalida al crear una anotación nueva (`_push_history` la limpia), igual que un editor de texto. Nuevo botón **Rehacer** en la barra junto a Deshacer. Soporta resaltado/subrayado/tachado/garabato (quads), rectángulo/elipse (rect), línea (con extremos) y tinta (trazos).
- **Rotar 90° a la izquierda (antihoraria)**: `_rotate` acepta ahora un `delta` (±90) y `_rotate_ccw` rota en sentido antihorario. Ambas direcciones están en el menú «Más opciones».
- **Eliminar anotación seleccionada con la tecla Supr (Delete)**: además del menú contextual.

### Changed
- **Barra de herramientas del visor reorganizada**: el menú «Más opciones» (⋮) pasa a la izquierda y agrupa las acciones poco frecuentes (guardar, imprimir, rotar en ambos sentidos, corregir orientación, insertar/duplicar/eliminar/mover página, cerrar pestaña). Los modos de vista (continuo/simple/doble) quedan en un grupo segmentado al centro. El botón del panel lateral se mueve al extremo derecho. La barra de anotaciones pega el menú de color junto a las herramientas en vez de empujarlo al borde.

## [0.1.17] - 2026-06-08

### Fixed
- **Censura y cajas OCR transpuestas en páginas rotadas (`/Rotate` 90/180/270, típico en escaneos)**: la imagen se mostraba derecha, pero al aplicar la censura el recuadro aparecía girado 90° (p. ej. una barra vertical a la izquierda en vez de horizontal arriba). Causa: las detecciones OCR y la vista previa viven en espacio de **pantalla** (el render respeta `/Rotate`), mientras que `add_redact_annot` escribe en espacio **sin rotar**. Ahora la censura se des-rota con `page.derotation_matrix` al aplicarse, y los resultados de texto nativo (`search_for`) se llevan a espacio de pantalla al recolectarse, de modo que vista previa y resultado coinciden en las 4 orientaciones.
- **OCR no cubría toda la página rotada**: `get_image_info().bbox` (sin rotar) se intersectaba con `page.rect` (rotado), recortando la región a un cuadrado y dejando sin OCR la parte inferior. Ahora el bbox se transforma a espacio de pantalla antes del recorte.
- **Selección de texto desalineada en páginas rotadas**: los caracteres nativos (`rawdict`) y los bloques (triple-toque) se mezclaban con las detecciones OCR en espacios distintos. Ahora todo se unifica en espacio de pantalla (overlay, hit-test contra el clic, orden de lectura) y el markup resultante se des-rota al escribirse.
- **Herramientas de dibujo y edición de anotaciones transpuestas en páginas rotadas**: dibujar (resaltado/rect/círculo/línea/flecha/tinta), seleccionar, mover y redimensionar quedaban girados. Se centralizó la conversión en la frontera de `AnnotationManager` (helpers `_to_page_rect`/`_to_screen_rect`/`_to_page_delta`): las entradas de pantalla se des-rotan antes de las APIs de PyMuPDF y la geometría devuelta para el overlay se rota a pantalla. El caso `rotation == 0` no cambia (las matrices son la identidad).
- **El botón «Rotar 90°» giraba la hoja pero no el contenido**: la ruta rápida de re-maquetado reutiliza los controles y no limpiaba la caché de render, así que tras rotar se volvía a mostrar el PNG cacheado SIN rotar dentro del contenedor ya girado (la hoja cambiaba de dimensiones pero el contenido se veía igual/aplastado). Ahora `_rotate` invalida la caché de render de la página y descarta sus cachés de texto/OCR (coordenadas obsoletas); el contenido se rota visualmente y, si había OCR, se limpia para re-ejecutarlo en la nueva orientación.
- **Selección de texto «en bandas» raras en páginas rotadas**: el barrido de selección asume renglones horizontales; en una página rotada el texto puede verse vertical en pantalla y se agrupaban caracteres de distintas columnas en bandas. Ahora el **orden de lectura, el barrido y la agrupación de líneas** se calculan en el marco donde el texto es horizontal y el resaltado se dibuja transformado a pantalla (los rects almacenados siguen en pantalla). El marco depende de la **fuente**: el texto **nativo** es horizontal en el espacio SIN rotar (p. ej. una hoja nativa que el usuario rotó 90°), mientras que las detecciones **OCR** son horizontales en pantalla (el OCR corre sobre la imagen ya derecha, p. ej. un escaneo con `/Rotate 270` que se ve recto). `_reading_frames(pn)` elige el marco según si la página tiene OCR; identidad si `rotation == 0`.
- **Resaltar/Subrayar/Tachar producían bandas / subrayado en el borde equivocado en escaneos rotados con OCR**: (1) el markup fusionaba los rects por renglón (`_line_merged_rects`) *después* de des-rotar, pero en ese espacio el texto OCR queda de lado → la fusión agrupaba mal → bandas. (2) además se pasaban **rects** des-rotados a `add_*_annot`, perdiendo la orientación del texto, así que el subrayado/tachado caía en el borde equivocado (líneas verticales al lado del texto). Ahora la fusión se hace en el marco de lectura correcto (pantalla para OCR, sin rotar para nativo) y se pasan **quads orientados** (`rect.quad * matriz`, que conservan las 4 esquinas) al espacio sin rotar de la página → el subrayado queda debajo del texto y el tachado por el medio (`_text_sel_apply` + `apply_text_tool(rects_are_final=True)`).

- **Texto OCR copiado salía sin espacios entre palabras**: la selección parte cada detección OCR en caracteres, dejando huecos de 0 px dentro de la palabra; pero las cajas de palabras OCR adyacentes se tocan o solapan (hueco ~0), así que el heurístico que infiere espacios por hueco no las separaba → al copiar salía todo junto. Ahora cada carácter lleva una marca `word_start` (primer carácter de cada detección) y la reconstrucción inserta el espacio en esa frontera. El texto nativo no la usa: sus huecos son reales y se infieren como antes.

### Added
- **Corrección automática de orientación para escaneos sin `/Rotate`**: nuevo botón en el visor («Corregir orientación del escaneo») que detecta cuántos grados está girado el contenido — usando los modelos OCR ya incluidos, sin descargas — y aplica `page.set_rotation` a todas las páginas para que se muestren derechas. No se guarda hasta que el usuario guarde el PDF.

## [0.1.16] - 2026-06-02

### Changed
- **Liberación del modelo OCR por inactividad en el extractor**: la pestaña de extracción ahora descarga el modelo OCR (varios cientos de MB de RAM) ~12 s después de terminar una búsqueda, replicando el patrón de timer del visor. Antes el modelo quedaba cargado en memoria durante toda la sesión una vez usado. El timer se cancela al iniciar/reanudar una extracción (para no descargar el modelo a mitad del trabajo) y se reprograma al finalizar; la siguiente extracción recarga el modelo de forma perezosa.
- **"Abrir con" abría ventana en blanco en Windows**: Flet 0.28 resetea `sys.argv` a `['']` en los builds empaquetados, perdiendo la ruta del PDF que Windows pasa al proceso. Ahora en Windows se lee la línea de comandos real del proceso vía `GetCommandLineW`/`CommandLineToArgvW` (Win32), que conserva el argumento intacto a nivel del SO. El comando de registro vuelve al formato estándar `"extraer_pdfs.exe" "%1"` (sin launcher externo). El flujo funciona tanto si la app ya está corriendo (instancia secundaria reenvía por IPC) como si no (instancia primaria abre el PDF directamente).

### Fixed
- **`ZeroDivisionError: division by zero` durante el OCR del extractor**: algunos PDFs reportan *bounding boxes* de imágenes que caen (total o parcialmente) fuera del área de la página; al recortarlas, PyMuPDF generaba un *pixmap* de 0 px en una dimensión y OnnxTR fallaba al calcular la relación de aspecto (`h / w`). Ahora las regiones se recortan al área de la página y se descartan las imágenes degeneradas (0 px) antes de la inferencia.
- **Registro de cierre de ventana en el log de diagnóstico**: se añade la línea `CLOSE | window closed by user` al cerrar la aplicación.
- **Logs de diagnóstico ampliados**: se registran casos que antes fallaban en silencio: contraseña requerida o incorrecta al abrir un PDF, errores genéricos de apertura (PDF corrupto, permisos, etc.), errores de comunicación IPC entre instancias, resultado del reenvío IPC desde la instancia secundaria, y fallos al traer la ventana al frente.

## [0.1.15] - 2026-05-31

### Changed
- **Visor escalable a documentos de cientos de páginas (virtualización del árbol de controles)**: cada página arranca como un *placeholder* liviano y su árbol pesado de controles (imagen, overlays de selección/anotación/OCR/censura, menús y `GestureDetector`) se construye bajo demanda al entrar en la ventana visible y se libera al alejarse. Antes se construían ~50 controles × N páginas al abrir el PDF (~40.000 para 800 páginas) → la carga se congelaba y la RAM se disparaba. Ahora abrir un PDF de 800 páginas es fluido y la RAM queda acotada a una ventana.
- **Selección de texto y arrastre de anotaciones fluidos en PDFs grandes**: la conversión de coordenadas viewport↔página (`_get_global_y` / `_get_page_and_local_y`) pasó de un barrido lineal O(N) por evento de arrastre a O(1)/O(log N) usando los offsets acumulados ya cacheados. Antes, seleccionar texto en la página 700 de 800 se sentía lento.
- **Scroll rápido sin hojas en blanco**: durante un *fling* rápido ahora se renderiza una vista previa de baja resolución (LOD) en vez de dejar la página en blanco; al detenerse se sube a calidad completa con *swap* sin parpadeo. El retardo de render tras detener el scroll bajó de 0.2 s a 0.1 s.
- **Atajos de zoom al estilo visor**: el zoom se activa con **Ctrl + `+`/`=` (acercar), `-` (alejar) y `0` (100%)** — una vez por pulsación, sin repetirse mientras se mantiene la tecla. Las teclas `+`/`-` a secas ya no hacen zoom (evita disparos accidentales). Nota: el zoom con **Ctrl+rueda** no es soportable de forma fiable en esta versión de Flet (el evento de scroll no incluye el modificador Ctrl y mantener solo Ctrl no emite evento de teclado), por lo que la rueda siempre hace scroll.

### Fixed
- **El visor perdía la página al cambiar de pestaña**: al volver a un PDF (desde otra pestaña, inicio, etc.) el scroll saltaba al inicio en vez de mantener la hoja en la que estabas. Ahora `on_focus` restaura la posición exacta de scroll.
- **`AttributeError: 'NoneType'` en selección de texto / panel OCR**: caminos de la GUI que recorrían las listas por página no toleraban los *slots* no construidos (placeholders) introducidos por la virtualización.
- **Ctrl+A / Ctrl+Z disparaban el zoom**: tras un atajo Ctrl+letra, un scroll inmediato con la rueda hacía zoom por error (Flet no emite *keyup*, así que el estado de Ctrl quedaba "pegado" durante ~1 s). Ahora cualquier atajo Ctrl+letra desarma el zoom-rueda explícitamente.

## [0.1.13] - 2026-05-21

### Changed
- **Módulo de agente IA refactorizado**: `_redact_agent_mixin.py` (~2100 líneas) se dividió en tres módulos independientes: `_redact_mixin.py` (búsqueda, términos, vista previa y aplicación de censura), `_profiles_mixin.py` (diálogos de gestión de perfiles de censura) y `_agent_mixin.py` (panel de chat y acciones rápidas del agente IA).

## [0.1.12] - 2026-05-21

### Added
- **Atajos de teclado completos en el visor**: Ctrl+Z (deshacer), Ctrl+A (seleccionar todo el texto), Ctrl+S (guardar), Ctrl+P (imprimir), Ctrl+C (copiar selección), Ctrl+O (abrir archivo), Ctrl+Inicio/Fin (ir a primera/última página), Escape (deseleccionar), Inicio/Fin, flechas, Re Pág/Av Pág, `+`/`-` (zoom), `W` (ajustar ancho), `F` (ajustar página).

### Changed
- **Vista previa de impresión rediseñada**: Las páginas ahora se muestran como una lista vertical desplazable (estilo filmstrip) con miniatura a la izquierda e información de página a la derecha, en lugar de una cuadrícula envuelta.
- **Apertura de archivos recientes más rápida**: Los módulos `pdf_viewer` y `pdf_security` se pre-cargan en segundo plano al iniciar la app, eliminando el retardo en el primer clic.

### Fixed
- **Doble apertura de archivos recientes**: Se agregó un guard `_opening_now` que previene abrir el mismo PDF dos veces si el usuario hace clic rápidamente o doble clic.
- **Ctrl+Scroll no se desactiva**: El modo zoom con Ctrl+Scroll ya no queda "pegado" después de soltar Ctrl. Ahora expira automáticamente en 1 segundo, restaurando el scroll normal sin necesidad de presionar otra tecla.

## [0.1.11] - 2026-05-20

### Changed
- **Manejo de instancia única en Windows mejorado**: La ventana se oculta antes de que Flutter la muestre al usuario, eliminando el parpadeo de ventana huérfana cuando la app ya está en ejecución.
- **IPC y conexión TCP optimizados**: Mejoras en el manejo de rutas iniciales y la conexión TCP en Windows para mayor fiabilidad al abrir PDFs con "Abrir con".

### Fixed
- Error de tipo en la firma de `_close_viewer_tab`.

## [0.1.10] - 2026-05-19

### Fixed
- Correcciones en el manejo de "Abrir con" y empaquetado en Windows.
- Mejoras en la compatibilidad de rutas y en la inicialización del IPC al usar `flet build`.

## [0.1.9] - 2026-05-19

### Changed
- **Eliminación de dependencias críticas**: Se removieron por completo los módulos de `pywin32` para solucionar conflictos en el empaquetado con `flet build windows` y garantizar la compatibilidad multiplataforma en Linux y macOS.
- **Rediseño de Instancia Única (IPC)**: Se migró la lógica en `main.py` hacia una solución nativa basada en sockets TCP locales combinados con un archivo de bloqueo (*lockfile*).
- **Módulo de Impresión Portátil**: Se reestructuró la lógica de impresión utilizando utilidades nativas de cada sistema operativo (PowerShell en Windows, y CUPS en Linux y macOS) en lugar de llamadas a la API de Windows.

## [0.1.8] - 2026-05-18

### Changed
- Se actualizaron los imports de pywin32 a nivel explícito para garantizar que flet build los detecte correctamente.
- Se movieron imports de win32print, win32ui, win32con desde imports dinámicos a explícitos en _print_mixin.py.

## [0.1.8] - 2026-05-18

### Changed
- Se publicó una nueva versión de release con la configuración de build ya alineada.

## [0.1.7] - 2026-05-18

### Changed
- Se agregó `pywin32` al bundle de Windows para que la detección de impresoras e IPC funcionen en producción.
- Se alineó la versión del instalador y del paquete con el release 0.1.7.

## [0.1.6] - 2026-05-18

### Added
- Notificaciones visuales de estado y errores para operaciones de impresión en el visor.
- Guardado explícito desde la app para impresoras PDF virtuales (por ejemplo "Microsoft Print to PDF").

### Changed
- Flujo de impresión mejorado: la app usa `FilePicker` para impresoras interactivas y evita bloquear la UI.
- Integración de impresión en Windows más robusta (soporte GDI directo cuando está disponible).

### Fixed
- Correcciones en el manejo del `FilePicker` para que los diálogos se muestren correctamente.

## [0.1.5] - 2026-05-15

### Added
- Apertura de PDFs desde el sistema operativo con soporte para "Abrir con" y reenvío a la ventana ya abierta.
- Comportamiento de instancia única para evitar que se abra otra ventana al lanzar un PDF cuando la app ya está en ejecución.
 - Mejoras en la selección de texto y en las herramientas de anotación: subrayado y tachado más precisos y fiables.

- Reanudación de extracción con PDFs protegidos en secuencias de múltiples archivos.

### Changed
 - Mejoras visuales en el visor: renderizado y estilos de anotaciones actualizados para mayor legibilidad.
- La extracción y la combinación de PDFs respetan mejor los documentos protegidos y mantienen la navegación en pestañas existentes.
- El instalador Inno Setup registra la asociación de `.pdf` para que la app aparezca como opción en "Abrir con".

### Fixed
- Corrección del flujo al abrir PDFs protegidos desde la integración del sistema operativo.
- Ajustes para continuar la extracción cuando hay más de un PDF protegido en el lote.

## [0.1.4] - 2026-05-14

### Changed
- Ajustes en seguridad de PDFs: ahora se utiliza `doc.save(..., encryption=...)` para crear PDFs protegidos, mejor compatibilidad con PyMuPDF.
- La pestaña `Seguridad` muestra los permisos reales del documento después de desbloquear.
- `remove_protection` ahora genera una copia sin cifrado de forma segura.

### Fixed
- Correcciones menores en la gestión de visibilidad de la UI para mostrar información de seguridad.

