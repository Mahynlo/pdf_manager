# Migración del visor a EmbedPDF

El visor (`app/ui/src/tools/viewer`) se pasa poco a poco a [EmbedPDF](https://www.embedpdf.com/docs/svelte/headless/introduction).
Se usa su modo *headless*: aporta la lógica y las piezas de dibujo, pero no estilos. Así se mantiene el
aspecto actual y se añade lo que EmbedPDF trae (formularios, firma, mosaico, gestos…).

Cada paso deja el visor completo y funcionando. Lo que aún no se migró sigue con el código actual.

## Pasos

| Paso | Qué cambia | Estado |
|---|---|---|
| 1. Render | PDFium (el motor de EmbedPDF) dibuja las páginas y las miniaturas en el navegador | Hecho |
| 2. Desplazamiento y zoom | `Viewport`, `Scroller`, Zoom, Tiling y Spread de EmbedPDF colocan y dibujan las páginas; nuestras capas (marcas, anotaciones) viven dentro de cada página | Hecho |
| 3. Selección de texto | Complemento Selection, con nuestra barra flotante (copiar, resaltar, censurar, explicar con IA) | Hecho |
| 4. Herramientas | Una a una: búsqueda (hecha), anotaciones y sellos (hechos), deshacer las operaciones de página (hecho; las hace Python), censura (hecha) e imprimir (hecho) | Hecho |

Al empezar cada paso hay que decidir qué hace Python y qué hace el navegador. Desde las anotaciones
el reparto es: **EmbedPDF edita el contenido del documento abierto** (por ahora, las anotaciones) y
**Python guarda el archivo** y hace lo pesado (OCR, censura por patrones, IA, combinar, seguridad).
En la censura, EmbedPDF pone las marcas y Python las aplica (ver «Censura»). Las operaciones de
página se quedan en Python: EmbedPDF no las tiene (ver «Operaciones de página»).

## Cómo se carga el documento (pasos 1 y 2)

Python es el dueño de las páginas y del archivo: abrir, guardar, censura, OCR y operaciones de
página. Las anotaciones las edita EmbedPDF en su copia (ver «Anotaciones», en el paso 4).

1. `viewer.document_url` serializa el documento abierto:
   - con sus anotaciones (las dibuja y edita la capa de anotaciones de EmbedPDF);
   - censura aplicada y páginas giradas o movidas;
   - sin cifrar, porque los bytes no salen del equipo y así PDFium no pide la contraseña. Se
     descifra una **copia**: guardar el documento abierto con `PDF_ENCRYPT_NONE` le quitaba el
     cifrado también para los guardados siguientes, y un PDF con contraseña abierto en el visor se
     guardaba sin ella (fallo corregido con las anotaciones; lo cubre una prueba).
2. Los bytes viajan en binario por un servidor local de un solo uso (`app/byte_server.py`, `Host.share_bytes`):
   - solo escucha en 127.0.0.1;
   - cada dato lleva un código aleatorio y caduca al primer uso o a los 2 minutos.
3. `canvas.js` los abre en EmbedPDF con su gestor de documentos (`openDocumentBuffer`). Cuando
   cambian las claves de página (girar, mover, insertar, censurar), abre la versión nueva y, en
   cuanto está lista, la pone a la vista y cierra la anterior. Mientras tanto se sigue viendo la anterior.

**Sin conexión a internet:**
- `pdfium.wasm` va dentro de la app (`import … from '@embedpdf/pdfium/pdfium.wasm?url'`, en `embed.js`);
  - su URL se pasa absoluta (`new URL(wasmUrl, location.href)`): el motor corre en un *worker* creado
    desde un `blob:` y no resuelve rutas relativas. Con `--dev`, Vite la da como `/node_modules/…` y el
    motor se quedaba esperando sin error: no se veía ninguna página;
- las fuentes de reserva remotas están desactivadas (`fontFallback: null`). Solo afectan a PDF en chino,
  japonés o coreano sin las fuentes incrustadas, que se dibujan con las fuentes internas de PDFium.

## Paso 2: desplazamiento, zoom y mosaico

**Piezas:**

| Archivo | Qué hace |
|---|---|
| `embed.js` | `registry()`: el registro de EmbedPDF, uno para toda la app, con el motor y los complementos: gestor de documentos, `viewport`, `scroll`, `spread`, `render`, `tiling` y `zoom` |
| `EmbedRoot.svelte` | La raíz `<EmbedPDF>` de ese registro; no dibuja nada |
| `PdfPages.svelte` | Uno por visor: registra nuestro contenedor como `Viewport` y dibuja las páginas con `Scroller`. `show(id)` cambia el documento a la vista |
| `PdfPage.svelte` | Una página: imagen de fondo (`RenderLayer`) y mosaico (`TilingLayer`) dentro de `Rotate`, y nuestras capas encima |
| `canvas.js` | `PageCanvas`: la misma API de antes (zoom, modos, ir a página, coordenadas, marcas) sobre las capacidades de EmbedPDF |

**Un registro para todos los visores:** los componentes de Svelte de EmbedPDF 2.15.1 leen el registro
de una variable global, así que solo puede haber un `<EmbedPDF>`. Con uno por visor, al abrir un segundo
PDF el primero fallaba («No se pudo mostrar el documento»). Ahora cada visor abre su documento en el
registro común con un id propio (`viewer-<id>-<versión>`), atiende solo los avisos de ese id y lo cierra
al cerrar la pestaña. Las pestañas ocultas no colocan sus páginas hasta que se ven.

**Cómo encaja con el resto del visor:**
- `canvas.el` sigue siendo el contenedor con scroll. Ahí escuchan el ratón la selección, el dibujo,
  el puntero y el recorte de OCR, sin cambios.
- Cada página tiene una capa del visor (`slots[i]`, `.pdf-page__layers`) con las anotaciones y las
  marcas (selección, búsqueda, OCR, censura).
  - Las capas existen siempre; al montar EmbedPDF una página, se enganchan a ella (`{@attach}`).
  - EmbedPDF solo monta las páginas cercanas a la vista. Por eso las búsquedas en las capas van por
    `canvas.queryAll(selector)` y no por el DOM.
  - Las barras flotantes (selección, anotación) se ocultan si su página no está montada.
- `canvas.pageRect(i)` da el rectángulo de una página en pantalla, esté montada o no.
- **Páginas giradas:** EmbedPDF dibuja cada página sin girar y espera que el componente `Rotate`
  (complemento `rotate`) la gire con CSS. Al principio del paso 2 faltaba y las páginas giradas se
  veían estiradas; se corrigió en el paso 3. Las miniaturas pasan el giro a `renderPage`.
- **Un componente por página** (`PdfPage.svelte`): el `Scroller` da objetos de página nuevos cada
  vez que cambia su estado. Si las capas se enganchaban leyendo ese objeto, se volvían a enganchar
  en cada cambio (al seleccionar, por ejemplo). Ahora dependen solo del número de página.

**Zoom y modos de vista:**
- La escala de EmbedPDF son píxeles por punto; nuestro 100 % son 2 px por punto, como en Qt (`UNIT`).
- **Ajustar ancho / página** usan los modos de EmbedPDF y se mantienen: al cambiar el tamaño de la
  ventana, abrir el panel lateral o girar una página, el zoom se recalcula. Antes se ajustaba una sola vez.
- **Ctrl+rueda** la lleva `canvas.js`: un paso de ratón es ×1,25, como antes. El trackpad da pasos
  más finos. La de EmbedPDF duplica el zoom en cada paso de ratón.
- **Pellizco** en pantallas táctiles: de EmbedPDF (`ZoomGestureWrapper`). Es nuevo.
- **Modos de vista:**
  - Continuo: estrategia vertical de EmbedPDF.
  - Página única y doble página son paginados: se ve una página o un par, y la rueda pasa de
    página en el borde. EmbedPDF no los trae; `embed.js` añade al complemento de scroll una
    estrategia `paged` que muestra solo una fila (`showRow`).
  - Doble página usa el complemento Spread (pares 1-2, 3-4…).

**Dibujo de las páginas:**
- `RenderLayer` dibuja la página entera a 1 px por punto como fondo: se ve enseguida al desplazarse.
- `TilingLayer` dibuja encima, en mosaicos de 768 px, solo la parte a la vista y a la resolución del zoom.
  Así, a mucho zoom no se rasteriza la página entera. Antes había un tope de 12 MP por página.
- Ambos con las anotaciones no editables y los formularios (`withAnnotations`, `withForms`), en WebP.
- Las miniaturas salen del mismo documento (`canvas.thumbnails`).

**Medidas** (PDF de 43 MB y 120 páginas con fotos, en la app):

| | Paso 1 | Paso 2 |
|---|---|---|
| Llevar el documento al navegador | 0,3 s | 0,3 s |
| Saltar a la página 80 | 0,39 s | 0,42 s (fondo y mosaico listos) |
| Asentarse tras un desplazamiento rápido de 12 000 px | — | 0,47 s |
| Páginas montadas | todas (huecos) | 5 |

**Comprobado** también en el ejecutable empaquetado (`pdfium.wasm` dentro del paquete; ver
[instalador.md](instalador.md)), y en la app real con eventos de ratón reales por CDP (`embed_e2e`, `interact_e2e`):
- páginas, mosaico y capas;
- anotación y marca de búsqueda en su sitio;
- zoom con botones y con Ctrl+rueda;
- ajustar ancho;
- los tres modos de vista, con la rueda pasando de página en el borde;
- tres PDF abiertos a la vez: cada pestaña con su zoom, girar en una no toca las demás y cerrar una deja bien el resto;
- girar recarga el documento y conserva la página;
- selección arrastrando, mano, miniaturas y modo noche.

El recorrido completo de la interfaz (`svelte_e2e`) termina sin errores de JavaScript.

**Qué se retiró:**
- `pdfium.js` y el lienzo propio: caché de imágenes, colocación de páginas y geometría de `layout.js`;
- en Python, `viewer.render` y `viewer.thumbnails`.

Ya no hay vuelta al render de Python: si el motor no carga, el lienzo muestra
«No se pudo mostrar el documento».

**Pendiente de este paso:** al mover, insertar, borrar o censurar se recarga el documento entero en
EmbedPDF (girar ya no: ver «Rendimiento y memoria»).
Medido en el PDF de 43 MB:
- la versión anterior se sigue viendo 0,44 s mientras se carga la nueva;
- después, las páginas a la vista quedan en blanco unos 0,15 s;
- a los 0,9 s todo está nítido.

Se queda: EmbedPDF no tiene operaciones de página (ver «Operaciones de página», en el paso 4).

## Paso 3: selección de texto

**Qué hace cada lado:**
- EmbedPDF (complemento Selection, con el gestor de interacción) calcula la selección con el texto
  que PDFium lee del documento: arrastrar (también entre páginas), doble clic (palabra), triple clic
  (línea, nuevo) y Ctrl+A (`setSelection` de la página entera). También da el texto seleccionado.
- `text.js` dibuja la selección con nuestras marcas (`.sel-rect`) y muestra nuestra barra flotante
  (copiar, resaltar, subrayar, tachar, censurar, buscar, Google, explicar con IA). Con las
  herramientas resaltar, subrayar y tachar, al soltar se crea la anotación, como antes.
- Desde el paso 4, la selección da a las anotaciones y a la censura sus partes
  (`getFormattedSelection`), que se convierten en anotaciones o marcas de EmbedPDF.

**El texto de OCR:** vive en Python (`entry.ocr`), no en el PDF. `viewer.document_url` lo escribe
como texto invisible en la copia que recibe EmbedPDF (`embed_ocr_words` en `pdf_core/text_layer.py`):
cada palabra ocupa su caja, también en páginas giradas, y se omiten las que tapan texto nativo (el
mismo criterio que la capa de texto). El documento guardado no cambia. Tras un OCR, el lienzo vuelve
a cargar el documento (`canvas.reload`).

**Cómo encaja con el resto del ratón:**
- Cada página va dentro de un `PagePointerProvider`, que pasa el ratón a la selección (y, desde el
  paso 4, a las anotaciones). Los eventos siguen subiendo al lienzo, donde escuchan las demás herramientas.
- Nuestras capas de marcas no reciben el ratón (`pointer-events: none`). La imagen y el mosaico de
  la página tampoco: EmbedPDF solo quita la selección de las anotaciones (y termina el texto libre)
  si el clic cae en la propia página.
- Con las herramientas de texto (seleccionar, resaltar, subrayar, tachar) el gestor de interacción
  está en el modo de texto; con las demás, en `viewer-tools`, donde la selección está apagada.
- EmbedPDF solo termina un arrastre con el `pointerup` de la página donde empezó. Si se suelta en
  otra página, entre páginas o fuera del lienzo, lo termina `text.js`.

**Coordenadas:** las de EmbedPDF son de la página sin girar; `text.js` las pasa a las de la página
tal como se ve (`transformRect`), que son las de nuestras capas y las de Python.

**Comprobado** con ratón y teclado reales por CDP, en la app compilada y con `--dev` (`sel_e2e`):
- arrastrar, copiar, doble y triple clic, Ctrl+A, Escape;
- la mano no selecciona;
- de una página a otra, incluida una girada;
- resaltar en una página girada deja la anotación sobre el texto y vuelve a la selección;
- doble clic sobre una anotación no selecciona el texto de debajo;
- una página escaneada no tiene texto; tras el OCR, el doble clic selecciona la palabra reconocida.

Los recorridos de los pasos anteriores (`svelte_e2e`, `embed_e2e`, varias pestañas) siguen sin
errores de JavaScript.

**Lo que cambia para quien usa el visor:**
- triple clic para seleccionar una línea;
- arrastrar tiene que empezar sobre texto (o muy cerca): desde el margen no selecciona. Antes se
  tomaba el carácter más cercano.

`viewer.text_layer` se retiró con el paso 4 (búsqueda): ya nada lo pedía desde la interfaz.

## Paso 4: herramientas

El objetivo de cada herramienta: usar lo que trae EmbedPDF donde es mejor y conservar lo nuestro
que EmbedPDF no tiene.

### Búsqueda (hecha)

La pestaña «Buscar» conserva su aspecto y sus atajos (Ctrl+F, Enter, F3 / Shift+F3, enviar el
término a la censura, buscar la selección), pero busca el complemento Search de EmbedPDF sobre el
documento a la vista, también en el texto de OCR (va en él como texto invisible).

**Lo que mejora:**
- los resultados aparecen mientras busca, página a página;
- sin tope de resultados (Python devolvía como mucho 2000);
- opción nueva «ab»: solo palabras completas;
- todas las coincidencias quedan marcadas en la página; la actual, más fuerte;
- el fragmento de cada resultado son palabras completas alrededor de la coincidencia.

**Cómo encaja:**
- `SearchPanel.svelte` habla con el complemento (`searchAllPages`, con las opciones de mayúsculas y
  palabra completa) y dibuja las marcas en las capas del lienzo (`.search-hit`, la actual con
  `.is-current`), pasando las coordenadas con `canvas.toView`.
- Tras una operación de página o un OCR el documento se vuelve a abrir en EmbedPDF; la búsqueda
  espera a que termine (`canvas.loading`) y se repite sobre la versión nueva.
- Antes de cambiar las opciones se para la sesión de búsqueda: si no, EmbedPDF lanzaba otra
  búsqueda por su cuenta, que la nuestra cancelaba (y lo registraba como error).
- La lista pinta 200 resultados y «Mostrar más»: con miles, pintarlos todos a la vez tardaba
  segundos. F3 abre más tramos si hace falta.

**Medidas** (PDF de 300 páginas con texto, en la app):

| Búsqueda | Python (antes) | EmbedPDF |
|---|---|---|
| «gato» | 2000 (tope), 2,7 s | 10 800, la primera a los 63 ms, todas en 1,25 s |
| «lluvia cae» | 2000 (tope), 0,58 s | 9 900, la primera a los 57 ms, todas en 1,1 s |
| sin resultados | 0,57 s | 0,49 s |

**Comprobado** con teclado y ratón reales por CDP (`search_e2e`, 16 comprobaciones): Ctrl+F, Enter,
F3 / Shift+F3, ir a un resultado de una página girada (la marca cae sobre la palabra), mayúsculas,
palabra completa, una frase partida entre dos líneas, sin resultados, limpiar, repetir tras girar
una página, encontrar el texto de OCR tras reconocerlo y «Buscar en el documento» desde la
selección.

**Retirado:** en Python, `viewer.search` y `viewer.text_layer`, y en `pdf_core/text_layer.py` lo que
solo servía para buscar y seleccionar (`search_layer`, `match_rects`, `snippet`, tramos y
posiciones de la capa). La capa de texto sigue para el asistente IA y el panel de OCR (`text_of`).

### Anotaciones y sellos (hechos)

Las anotaciones las dibuja y edita el complemento Annotation de EmbedPDF (con su historial para
deshacer y rehacer). Se conservan nuestras herramientas, la paleta, la barra de propiedades, los
sellos y leyendas, y que tras dibujar una forma se vuelve al puntero con ella seleccionada.

**Herramientas** (barra del lienzo):

| Grupo | Herramientas |
|---|---|
| Texto seleccionado | Resaltar, subrayar, tachar, subrayado ondulado, indicar texto omitido (marca de inserción con el texto que falta) y reemplazar (tacha lo seleccionado y guarda el texto nuevo, agrupados) |
| Formas | Rectángulo, círculo, línea, flecha, polilínea y polígono (clic en cada vértice, doble clic para terminar) |
| Trazos | Pluma, marcador (translúcido) y trazo fino |
| Texto e imagen | Texto libre; con clic derecho, llamada (texto con flecha) y nota; imagen (elige un archivo y se coloca con un clic) |

Las de texto seleccionado las crea `annotations.js` (`markup`), como antes; las demás son las
herramientas de EmbedPDF con nuestro estilo. Indicar y reemplazar texto piden el texto en un
diálogo; con doble clic (o «Editar texto» en la barra) se cambia, como el de una nota.
No se incluyen los enlaces de EmbedPDF: sus destinos apuntan a páginas y Python conserva los del
documento al guardar.

**Lo que mejora:**
- las anotaciones que ya trae el PDF se ven y se editan con su apariencia original (antes se
  convertían a nuestro modelo y se perdía lo que no cabía en él);
- editar ya no recarga nada: deshacer y rehacer son instantáneos (antes, una llamada a Python por cambio);
- tiradores de EmbedPDF: redimensionar, mover los extremos de una flecha, girar formas y texto;
- texto libre editado en la página con su tipo de letra real; mientras se escribe se ve todo lo
  escrito y, al terminar, la caja crece hasta que quepa (`_fitText`: ancho de la línea más larga,
  sin pasar del borde de la página, y alto de todas las líneas; nunca encoge). Se termina con un
  clic fuera, con Esc (queda seleccionado) o al quitar la selección (la X de la barra): EmbedPDF no da cómo cerrar la edición, así que `canvas.finishEditing` le da el clic
  en el fondo de la página que la cierra;
- los resaltados, subrayados y tachados son anotaciones de marca de texto (antes, rectángulos);
- las miniaturas salen dibujadas con las anotaciones (antes, un SVG encima); al cambiar una
  anotación se rehace solo la de su página, sin parpadeo (se ve la anterior hasta que llega la nueva).

La barra de propiedades va debajo de la selección, centrada (encima si no cabe, dejando libre el
tirador de giro de EmbedPDF), y encima mientras se escribe un texto libre.

**Reparto con Python:**
- EmbedPDF las edita en su copia del documento. Antes de lo que necesita el documento al día en
  Python (guardar, «Guardar como», exportar una página, cambiar páginas, censurar, OCR),
  `annotations.js` (`sync`) sube la copia (`saveAsCopy`) por el servidor local
  (`ByteServer.expect`, `POST`, `Host.upload_url`) y `viewer.sync_annotations` toma de ella solo las
  anotaciones (`pdf_core/annot_transfer.py`): se injertan como objetos PDF, sin perder tipos ni
  apariencias. El resto del documento (contenido, cifrado) sigue siendo el de Python, y el texto de
  OCR que la copia lleva como texto invisible no pasa al archivo.
- Se quedan los formularios y los enlaces del documento: el visor no los edita (los enlaces están
  bloqueados en EmbedPDF) y sus destinos apuntan a páginas.
- `viewer.annotations_changed` avisa del primer cambio: así Python sabe que hay cambios sin guardar
  (aviso al cerrar la pestaña o la app).
- Tras una operación de página, censura u OCR se reabre la versión de Python: el historial de
  deshacer empieza de nuevo (como antes tras cambiar páginas).

**Piezas:**

| Archivo | Qué hace |
|---|---|
| `palette.js` | Colores y estilos (solo datos; también los valores iniciales de las herramientas en `embed.js`) |
| `annotations.js` | `Annotations`: estilo por visor, marcas de texto, sellos, crear/cambiar/borrar, deshacer, aviso de cambios y `sync` con Python |
| `editing.js` | `AnnotationEditor`: barra de propiedades (color, grosor, letra, relleno, editar nota, traer al frente, enviar al fondo, duplicar, eliminar), teclado (Supr, Esc, Ctrl+D, flechas) y doble clic en una nota |
| `PdfPage.svelte` | `AnnotationLayer` de EmbedPDF dentro de cada página |
| `canvas.js` | `ANNOTATION_TOOL`: herramienta de EmbedPDF de cada herramienta de dibujo (rectángulo → `square`, flecha → `lineArrow`, pluma y trazo fino → `ink`, texto → `freeText`, nota → `textComment`) |

**Lo que cambia para quien usa el visor:**
- varias anotaciones se seleccionan con Ctrl+clic (antes, Mayús+clic);
- la pluma y el marcador juntan los trazos que se hacen seguidos (menos de 0,8 s) en una sola anotación;
- «Traer al frente» y «Enviar al fondo» (barra de propiedades): EmbedPDF dibuja las anotaciones en
  el orden de la página y no sabe cambiarlo, así que `Annotations.reorder` borra las que tienen que
  quedar encima (al fondo: las que hay delante) y las vuelve a crear al final, con id nuevo. Con el
  mismo id no funciona: EmbedPDF descarta la nueva mientras el borrado está pendiente. Apunta su
  propia orden en el historial: al deshacer, EmbedPDF devolvería lo borrado al final, así que se
  vuelve a llevar al final todo lo que había desde la primera movida, en el orden de antes
  (comprobado en `annot_e2e`: al frente, al fondo, Ctrl+Z, Ctrl+Y y guardado). Los
  grupos (reemplazar texto) se rehacen enteros y se vuelven a enlazar. Una imagen no se puede
  volver a crear (su objeto no lleva la imagen): no se mueve ni se puede enviar algo al fondo si
  tiene una imagen encima (aviso). Las anotaciones que ya traía el PDF, al rehacerse, toman la
  apariencia que les da EmbedPDF.

**Svelte fijado en 5.51.0:** los componentes de EmbedPDF 2.15.1 vienen compilados con un Svelte
anterior a 5.51.1, que guardaba los manejadores de eventos delegados en `elemento.__pointerdown`.
Desde 5.51.1 el runtime los busca en otra propiedad y los ignora: ningún clic sobre una anotación
llegaba a EmbedPDF (no se podía seleccionar, mover ni redimensionar). Al pasar a EmbedPDF 3 (aún en
*next*), comprobar si ya viene compilado con un Svelte reciente antes de subir de versión.

**Comprobado** con ratón y teclado reales por CDP (`annot_e2e`, 34 comprobaciones): la anotación
del PDF se ve y se selecciona con un clic; Supr y Ctrl+Z; resaltar desde la barra de la selección y
con la herramienta en una página girada; rectángulo (vuelve al puntero con la barra), pluma, texto
libre, nota (pide su texto) y sello; Ctrl+S guarda todo y conserva el enlace; tras girar una página
siguen las anotaciones; ondulado, indicar y reemplazar texto (con su texto), línea, polilínea,
polígono, marcador, llamada e imagen (el selector de archivos se intercepta por CDP), y todas se
guardan en el PDF. La app se cierra sin errores de MuPDF. Siguen pasando `sel_e2e` (14), `search_e2e` (16) y `svelte_e2e`, sin
errores de JavaScript.

**Retirado:** `services/annotation_store.py`, `pdf_core/annotations.py` y las llamadas
`viewer.add_annotations`, `update_annotations`, `delete_annotations`, `reorder_annotations`, `undo` y `redo`.

### Operaciones de página (las hace Python, ahora con deshacer)

El plan era pasarlas a PDFium para que fueran instantáneas. **EmbedPDF 2.15.1 no lo permite:** el
motor solo expone borrar e importar páginas (no girar, mover ni crear), ningún complemento las
gestiona (la acción `SET_PAGES` del núcleo no la usa nadie) y la versión 3 (prerelease) tampoco las
trae. Hacerlas por nuestra cuenta en el worker de PDFium sería frágil: las anotaciones de EmbedPDF
van por número de página y se descolocarían al mover páginas.

Así que siguen en Python (girar, insertar en blanco, duplicar, borrar, mover, corregir la
orientación) y ahora **se pueden deshacer y rehacer**:
- cada operación guarda su inversa (`_PageStep` en `services/viewer.py`): girar al revés, devolver
  la página a su sitio, quitar la insertada; la página borrada se guarda aparte, con sus
  anotaciones, para devolverla. Hasta 30 pasos;
- `viewer.undo_pages` / `viewer.redo_pages` devuelven el documento y a qué página ir; `_info` dice
  si hay algo que deshacer o rehacer (`page_undo`, `page_redo`);
- al deshacer un giro vuelven las palabras de OCR de esa página (al girarla se pierden);
- una página borrada y devuelta es un objeto nuevo del PDF: el documento sigue con cambios sin
  guardar aunque se deshaga todo. Deshacer un giro o un movimiento sí vuelve a lo guardado.

**Un solo Ctrl+Z** (y el botón «Deshacer»): primero deshace lo de EmbedPDF (anotaciones) y, cuando
no queda nada, la última operación de página. Tras una operación de página EmbedPDF empieza un
historial nuevo, así que el orden se respeta: lo hecho después de girar se deshace antes que el giro.
Lo que se pierde: lo que quedaba por rehacer en las anotaciones al deshacer una operación de página.

**Comprobado** (`annot_e2e`, ahora 53 comprobaciones): girar, Ctrl+Z, Ctrl+Y y Ctrl+Z otra vez, con las
anotaciones de la página en su sitio. En Python, `test_viewer_undoes_and_redoes_page_operations`.

### Censura (hecha): EmbedPDF marca, Python aplica

Complemento `redaction` de EmbedPDF en **modo anotación**: cada marca pendiente es una anotación
`Redact`. Se ve con borde rojo y, al pasar el ratón, con el relleno que tendrá; se selecciona, se
mueve, se redimensiona (las de área), se borra (Supr) y se deshace (Ctrl+Z) como las demás
anotaciones. Antes, la vista previa era una capa nuestra que no se podía tocar.

**Quién hace qué:**
- **Marcas** (`tools/viewer/redaction.js`, `RedactionMarks`). Las ponen:
  - los términos, patrones y perfiles del panel: Python busca dónde aparecen (`redact.find`, con
    nuestras reglas: sin tildes, palabra completa, regex, texto de OCR) y se pone una marca en cada
    coincidencia;
  - «Enviar selección a censura» (barra de la selección): una marca con la forma del texto;
  - la herramienta **Marcar** del panel (`TOOLS.REDACT`, la herramienta `redact` de EmbedPDF):
    arrastrar sobre el texto lo marca y arrastrar en otro sitio marca un área. Esc la termina.
- Cada marca guarda lo que la puso: el término en `/Contents` y el tipo en `/Subj` (`texto`,
  `regex`, `selección` o `manual`). **La lista del panel se calcula de las marcas**: borrar una
  suelta, deshacer o rehacer se ve en la lista sin más. Quitar un grupo borra todas sus marcas.
- Un término o patrón con muchas coincidencias se deshace de **un solo Ctrl+Z**: `Annotations.batch`
  junta las órdenes que EmbedPDF apunta en su historial (una por anotación) en una sola.
- El color del panel es el relleno de todas las marcas (`/IC`).
- **Aplicar**: las marcas pasan a Python con las demás anotaciones (`sync`) y `redact.apply` →
  `ViewerService.apply_redaction_marks` las aplica con PyMuPDF (`pdf_core.redaction.apply_marks`):
  se borra lo de debajo, también las palabras de OCR, y la página cambia de clave. Python aplica y
  no PDFium porque `sync` solo pasa anotaciones: el contenido borrado por PDFium no llegaría.
- Se quita `/RO` de cada marca antes de aplicarla (apariencia que escribe EmbedPDF; MuPDF la ignora
  y avisaba por consola).

**Conservado:** términos, patrones ⚡, Aa (mayúsculas), W (palabra completa), buscar en OCR,
perfiles (guardan los términos del panel, no las selecciones ni las áreas), colores, censura desde
«Buscar» y desde la IA, «solo se guarda como copia».

**Cambia:**
- al cambiar Aa, W u OCR, los términos se buscan de nuevo: sus marcas se rehacen (se pierden las
  que se hubieran borrado a mano de esos términos);
- cargar un perfil sustituye los términos de la lista; las selecciones y las áreas se quedan;
- el OCR nuevo no añade marcas solo: hay que volver a añadir el término;
- la marca no se pone sobre un término que no aparece (aviso «No se encontró»);
- sin el botón de vista previa (las marcas solo tienen borde: el texto se lee);
- unas marcas sin aplicar se guardan en el PDF como anotaciones de censura (como Acrobat).

**Piezas:** `PdfPage.svelte` da a la capa de anotaciones los dibujantes de las marcas
(`annotationRenderers={redactRenderers}`) y monta `RedactionLayer` (lo que se dibuja mientras se
marca) y `MarqueeSelection` (el rectángulo arrastrando: sin él, la herramienta no marca áreas; en la
selección de texto está apagado). Mientras se marca, `text.js` no muestra su barra: la selección
es del complemento de censura.

**Comprobado** (scratchpad `redact_e2e.py`, 17 comprobaciones, también en modo desarrollo): término
(con la página girada), patrón, borrar una marca y deshacer, Ctrl+Z del patrón de una vez, marcar un
área y un texto, Esc, selección enviada, color, aplicar, y la búsqueda ya no encuentra lo censurado.
En Python, las pruebas `test_redact_*` (las marcas las pone la prueba en la copia, como el visor).

**Retirado:** `redact.add_term`, `add_region`, `remove_term` y `clear` (la lista son las marcas),
`ViewerService.apply_redactions`, `pdf_core.redaction.apply` y la vista previa `.redact-preview`.

### Imprimir (hecho): las páginas las dibuja PDFium

Se queda nuestro diálogo (rango, subconjunto, orden inverso, orientación por página, color, escala
y vista previa) y la impresión del navegador (`print.js`: `#print-root` y `window.print()`). Lo que
cambia es quién dibuja las hojas: antes Python (`viewer.print_images`, tras pasarle las anotaciones);
ahora PDFium en el navegador (`canvas.pageImages`: `renderPage` con las anotaciones, a 150 ppp, o a
60 para la vista previa; en grises, pasando la imagen por un canvas). Así sale lo mismo que se ve,
sin esperar a Python ni mandar las imágenes en base64 por el puente. Antes se escriben en el PDF de
EmbedPDF las anotaciones pendientes (`annotations.commit`).

No se usa el complemento `print` de EmbedPDF: prepara un PDF y lo imprime con el visor de PDF del
navegador en un marco oculto, sin nuestras opciones (subconjunto, orientación, escala, grises) y
con dudas en WebView2. Las páginas a imprimir las sigue calculando Python (`viewer.print_selection`,
`pdf_core.page_ranges`).

**Comprobado** (`annot_e2e`, sustituyendo `window.print`): vista previa, hoja de 1240×1754 px (A4 a
150 ppp) con las anotaciones, y en grises.

**Retirado:** `viewer.print_images` y el parámetro `gray` de `imaging.page_data_url`.

## Rendimiento y memoria

Medido el 2026-10-30 con el PDF de 43 MB y 120 páginas (scratchpad `perf_probe.py`: memoria privada
de Python y de los procesos de WebView2 de la app, por tipo).

| Momento | Python | WebView2 | Total |
|---|---|---|---|
| Abierto | 100 MB | 570 MB | 670 MB |
| Tras recorrerlo entero | 101 MB | 1,29 GB | 1,39 GB |
| Tras 6 giros, antes del cambio | 100 MB | 1,61 GB | 1,71 GB |
| Tras 6 giros, ahora | 101 MB | 1,31 GB | 1,41 GB |

**Qué ocupa:**
- Python, unos 100 MB y estable. Abrir 0,2 s, preparar el documento para el visor 0,17 s, girar 0,02 s.
- El proceso de GPU es una caché de Chromium con tope: unos 575 MB mientras se recorre y 82 MB tras
  30 s sin hacer nada.
- El renderizador (página y motor PDFium) crece unos 200 MB por cada recorrido entero, pero casi
  todo es basura que se recoge sola (de 1 GB a 528 MB tras 30 s quieto). Lo que queda de más es el
  máximo que alcanzó la memoria de PDFium (WebAssembly no la devuelve).

**Cambios:**
- **Girar sin recargar** (`canvas._turnInPlace`): antes cada giro mandaba y cargaba otra vez el
  documento entero (en EmbedPDF, tres copias del PDF a la vez hasta que se recogían) y crecía ~45 MB
  por giro. EmbedPDF abre los documentos con el giro «normalizado» (todo en la página sin girar; el
  giro solo para mostrarla), así que basta con cambiar `page.rotation` en su estado, avisar con
  `refreshPages` (no hay acción para girar una página) y recolocar (`refreshDocumentLayout`). El
  historial de EmbedPDF se vacía, como al recargar, para que Ctrl+Z siga el orden de siempre.
- **Miniaturas**: al llegar la versión nueva de una página (cambiaron sus anotaciones), se libera
  la anterior (antes se quedaban hasta llenar la caché de 600).
- **Ventana minimizada**: se pide a WebView2 que use poca memoria
  (`CoreWebView2.MemoryUsageTargetLevel = Low`, en `app/host.py`) y al restaurarla, normal. Medido:
  el renderizador baja de 615 a 429 MB y la página vuelve a dibujarse en 0,2 s.

**Descartado:**
- abrir por URL con peticiones por rangos (EmbedPDF lo permite): Python tendría que guardar el PDF
  entero en su servidor mientras está abierto (la memoria solo cambia de sitio) y cada página iría
  más lenta;
- el envío del PDF al worker de PDFium es una copia (EmbedPDF no lo transfiere): solo se arregla
  cambiando EmbedPDF.

## Paquetes

En `app/ui/package.json`, con versiones fijas (todas iguales, 2.15.1):
- `@embedpdf/core`, `@embedpdf/engines`, `@embedpdf/pdfium`;
- `@embedpdf/models`: geometría (`transformRect`);
- los complementos `document-manager`, `viewport`, `scroll`, `spread`, `rotate`, `render`, `zoom`,
  `tiling`, `interaction-manager`, `selection`, `search`, `annotation`, `history`, `export` y
  `redaction`.

Y `svelte` fijado en 5.51.0 (ver «Anotaciones y sellos»).

Las miniaturas salen de `render` (`canvas.thumbnails`), no del complemento `thumbnail`, que se quitó:
el panel lateral ya tiene su propia lista virtual y sus tarjetas.

La interfaz compilada crece unos 5,4 MB: `pdfium.wasm` (4,6 MB) y el *worker* (0,7 MB).
