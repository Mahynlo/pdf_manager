# Changelog

## [No publicado]

### Added
- **Censura — interruptor «Solo palabras completas»**: nuevo botón en el panel de censura (junto al de mayúsculas) para que un término coincida **solo como palabra entera** — buscar «la» ya **no** coincide dentro de «tabla» o «regla». PyMuPDF no tiene un flag nativo de palabra completa (`search_for` siempre hace matching de subcadena), así que el modo se implementa matcheando contra los **tokens** de `get_text("words")` por igualdad (con paridad en la búsqueda OCR vía límites `\b`). **Activo por defecto** (es lo esperable al censurar términos concretos y evita la explosión de coincidencias). El estado se **persiste en los perfiles** de censura (campo `whole_word`, junto a `case_sensitive`/`color`); perfiles antiguos sin el campo asumen `True`. Verificado: en «la tabla de la casa regla», subcadena = 4 coincidencias, palabra completa = 2.

### Fixed
- **Censura — congelamiento al buscar palabras muy comunes («de», «la», «las»…)**: la búsqueda se trababa por dos motivos, ya corregidos. (1) `_find_term_matches` llamaba a `page.get_textbox(r)` (código nativo) **por cada coincidencia** para una etiqueta que **nunca se usa** (ni `_apply_redaction` ni la vista previa la leen) — con una palabra común eran miles de llamadas desperdiciadas; ahora se guarda el término directamente. (2) Se añadió un **cortacircuitos** (`_REDACT_MAX_MATCHES = 1000`): al alcanzar el tope se corta el barrido y, en la ruta interactiva, se avisa al usuario que refine el término (las rutas de lote cortan en silencio). Combinado con el nuevo modo «palabra completa» (activo por defecto), buscar conectores comunes deja de saturar el hilo de UI.

### Changed
- **Visor — optimizaciones de eficiencia en caminos calientes (sin cambio de comportamiento)**: cuatro mejoras que reducen el *coste*, no la salida (verificadas con tests en verde y equivalencia exacta de resultados). El trabajo pesado ya corre en C nativo dentro de PyMuPDF/onnxruntime; estas optimizaciones atacan el pegamento Python a su alrededor (ver `docs/visor-pdf.md` §12). (1) **`_get_page_words`**: el bucle Python que arma los miles de caracteres del `rawdict` ahora corre **fuera del `_doc_lock`** (la extracción nativa sigue dentro) — antes seleccionar texto en una página densa retenía el mismo lock que usan los workers de render y **bloqueaba el render de las páginas vecinas**. (2) **`_sort_words_column_aware`**: las claves del orden de lectura column-aware se **precomputan una vez por palabra** en vez de recomputar la multiplicación de matriz 2–3 veces por palabra en el `key` del sort → +24 % en páginas normales y **+211 %** en páginas rotadas, con salida byte-idéntica. (3) **`_point_has_text`** (cursor de hover): el barrido **O(W) lineal** sobre todas las palabras de la página en *cada* movimiento del ratón se reemplaza por un **índice de bandas en Y O(k)** (cada palabra indexada en todas las bandas que abarca → prueba exacta) → de **~16 ms a ~0.24 ms por hover (66.8×)** en una página de 2635 palabras, con 0 discrepancias. (4) **Búsqueda de censura**: cargar un perfil con N términos (o el lote del agente IA) re-extraía el texto de **todas** las páginas **por cada término** (`N × P` `get_text`); ahora un **caché de texto local al lote** (efímero, sin riesgo de quedar obsoleto) extrae cada página **una sola vez** (`P`) → cargar un perfil de 20 términos sobre 60 páginas baja de **~5.3 s a ~0.3 s (18.7×)**. Con `text_cache=None` (añadir un término a mano) el comportamiento es idéntico al anterior.

## [0.1.19] - 2026-06-09

### Added
- **Mover una anotación de una página a otra arrastrando**: con la herramienta de cursor, al arrastrar una anotación seleccionada (cuadrado, círculo, línea, flecha, tinta) más allá de los límites de su página, ahora **cambia de página** y se suelta en la de destino, en la posición del cursor. El arrastre de "mover" pasó a ser **absoluto** (offset puntero→caja) en vez de incremental, para que el salto de coordenadas al cruzar de página no descuadre la posición; el *ghost* de la forma se previsualiza en la página destino mientras se arrastra. La escritura al documento ocurre **una sola vez al soltar**: la anotación se recrea en destino (vía snapshot/recreate, `move_annot_to_page`) y solo entonces se borra del origen, de modo que un fallo no la pierde. Redimensionar (tiradores) sigue acotado a la página de origen.

### Changed
- **Vista previa de impresión tipo visor con scroll**: el panel de vista previa del diálogo de impresión pasa de una lista compacta (miniatura pequeña + texto "Página/Orden") a una **columna scrollable de "hojas" grandes centradas**, como un visor por el que se desplaza página a página. Cada hoja usa `CONTAIN` sobre fondo blanco papel → la página se ve **completa y con su proporción real** (antes `COVER` recortaba el contenido y deformaba las páginas apaisadas), con sombra de papel y un rótulo "Página N" debajo. Se quitó la etiqueta "Orden" (redundante: las páginas siempre van en orden ascendente). El diálogo es algo más grande y la caché de miniaturas de impresión (antes sin acotar) **se libera al cerrar** para no dejar PNG en RAM tras imprimir un PDF grande.
- **Combinar PDF: miniaturas más eficientes (menos aperturas de PDF y sin bloquear la UI)**: (1) el renderizado de miniaturas ahora es **por lotes** — `render_thumbnails_batch` abre el PDF **una sola vez** para todas las páginas pendientes, en vez de reabrir y reparsear el documento por cada página (antes, mostrar las miniaturas de un PDF de N páginas hacía N `fitz.open`). (2) Las celdas de la lista de chips y de la cuadrícula de previsualización pasan a **solo-cache** (`peek`, nunca renderizan al construirse): el render lo hace el worker en segundo plano (`warm_many`) y al terminar refresca, así que reconstruir la UI ya no dispara renders síncronos en el hilo de Flet (que reabrían el PDF por página y lo congelaban con muchas páginas). El visor a pantalla completa (lightbox) mantiene el render bajo demanda de una página.
- **Previsualización de dibujo de formas más fiel y fluida**: al dibujar un **círculo/elipse** o un **rectángulo**, la previsualización en vivo ahora muestra el **contorno de la forma real** (elipse inscrita / contorno del rectángulo) en el canvas de la página, en lugar de un `Container` rectangular relleno — antes un círculo se veía como un cuadrado hasta soltar el ratón. El contorno coincide con el resultado final (las formas se crean solo con trazo, sin relleno) y usa el color de trazo de la herramienta. Unifica la previsualización con la de línea/flecha/tinta. Además, el **trazo a mano alzada (tinta)** descarta micro-movimientos (< 2 px en pantalla) antes de añadir cada punto, reduciendo la reserialización del canvas por frame para un trazo más fluido (el trazo final ya se simplifica con RDP, así que no hay pérdida perceptible).
- **Tiradores de punto medio en la caja de selección**: además de las 4 esquinas (que redimensionan ambos ejes), la caja muestra ahora un tirador en el **punto medio de cada lado** que redimensiona **un solo eje** — estirar solo arriba/abajo (más alto/bajo) o solo izquierda/derecha (más ancho de un lado u otro), sin alterar la dimensión perpendicular. Aplica a todas las formas redimensionables (cuadrado, círculo, línea, flecha, tinta); las anotaciones de marcado de texto siguen sin tiradores. La detección prioriza las esquinas sobre los puntos medios en cajas muy pequeñas.
- **La caja de selección representa la forma y ya no "pierde" la figura al moverla**: al seleccionar un **círculo** o **rectángulo**, el overlay dibuja ahora un *ghost* con el **contorno real** de la figura (elipse/rectángulo, en su color de trazo) dentro de la caja, y el marco rectangular de tiradores se atenúa (1 px claro) para que la forma sea el elemento dominante (antes la caja era un cuadrado aun para un círculo). Como el *ghost* se redibuja en cada refresco del overlay, **sigue a la figura al mover/redimensionar** — antes, durante el arrastre se ocultaba la anotación real y solo se desplazaba la caja vacía, dando la sensación de que la figura desaparecía. Coste mínimo: una sola forma de canvas por refresco. (Línea/flecha/tinta conservan el marco rectangular por ahora.)

### Fixed
- **"Abrir con" abría una ventana en blanco (de verdad esta vez)**: el arreglo de 0.1.16 (`GetCommandLineW`) solo funciona en desarrollo. En el **exe empaquetado** por `flet build windows`, pasar CUALQUIER argumento (ni la ruta posicional ni `--dart-entrypoint-args`) impide que el runner de Flutter arranque el backend de Python: queda una ventana de Flutter en blanco y el workaround de `GetCommandLineW` nunca llega a ejecutarse. Verificado por el log diagnóstico: con argumento, Python no escribe ni la línea `LAUNCH`. Lo que sí funciona es lanzar el exe **sin argumentos** con la ruta en la variable de entorno `EXTRAR_PDF_PATH`. Solución: un pequeño **`launcher.exe`** nativo (C/Win32, `launcher/launcher.c`) al que ahora apunta el registro de "Abrir con". El launcher recibe la ruta sin problema (es un exe normal) y (1) la reenvía a la instancia abierta por el socket IPC `127.0.0.1:57423` —mismo protocolo `u32`+JSON UTF-8, sin parpadeo de ventana— o (2) si no hay instancia, lanza `extraer_pdfs.exe` con `EXTRAR_PDF_PATH`. El instalador ahora compila el launcher (`build.ps1`), lo registra como handler del ProgID, le pone `FriendlyAppName`/`SupportedTypes` y oculta el exe crudo de "Abrir con" (`NoOpenWith`) para que nadie elija la variante que se queda en blanco.

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

