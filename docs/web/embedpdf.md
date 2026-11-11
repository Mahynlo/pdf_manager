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
| 4. Herramientas | Una a una: búsqueda (hecha), anotaciones (hechas), sellos y firmas (hechos), deshacer las operaciones de página (hecho), censura (hecha) e imprimir (hecho) | Hecho |
| 5. EmbedPDF, dueño del documento | Ver «EmbedPDF, dueño del documento del visor»: etapas 1 (operaciones de página) y 2 (guardar, extraer una página, propiedades e imprimir) hechas | En curso |

Al empezar cada paso hay que decidir qué hace Python y qué hace el navegador. El reparto (decidido
el 2026-11-10, para que la app gaste menos en escritorio y en el navegador): **EmbedPDF es el dueño
del documento abierto en el visor** (anotaciones, operaciones de página, las copias que salen del
visor al guardar, extraer una página o imprimir y, en la etapa siguiente, el texto del OCR) y
**Python hace lo que EmbedPDF no sabe**: OCR, IA, orientación automática,
censura por patrones y las herramientas de archivos (Unir, Extraer, Dividir, Seguridad). En la censura,
EmbedPDF pone las marcas y Python las aplica (ver «Censura»).

## Cómo se carga el documento (pasos 1 y 2)

Python abre el archivo y da al visor su versión. Desde ahí, EmbedPDF edita el documento abierto
(anotaciones y páginas); lo que cambia Python (censura, OCR) vuelve a abrirse en EmbedPDF.

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
3. `canvas.ts` los abre en EmbedPDF con su gestor de documentos (`openDocumentBuffer`). Cuando
   Python cambia las páginas (censura, OCR), abre la versión nueva y, en cuanto está lista, la pone
   a la vista y cierra la anterior. Mientras tanto se sigue viendo la anterior. Las operaciones de
   página no vuelven a abrirlo (ver «EmbedPDF, dueño del documento del visor»).

**Sin conexión a internet:**
- `pdfium.wasm` va dentro de la app (`import … from '@embedpdf/pdfium/pdfium.wasm?url'`, en `embed.ts`);
  - su URL se pasa absoluta (`new URL(wasmUrl, location.href)`): el motor corre en un *worker* creado
    desde un `blob:` y no resuelve rutas relativas. Con `--dev`, Vite la da como `/node_modules/…` y el
    motor se quedaba esperando sin error: no se veía ninguna página;
- las fuentes de reserva remotas están desactivadas (`fontFallback: null`). Solo afectan a PDF en chino,
  japonés o coreano sin las fuentes incrustadas, que se dibujan con las fuentes internas de PDFium.

## Paso 2: desplazamiento, zoom y mosaico

**Piezas:**

| Archivo | Qué hace |
|---|---|
| `embed.ts` | `registry()`: el registro de EmbedPDF, uno para toda la app, con el motor y los complementos: gestor de documentos, `viewport`, `scroll`, `spread`, `render`, `tiling` y `zoom` |
| `EmbedRoot.svelte` | La raíz `<EmbedPDF>` de ese registro; no dibuja nada |
| `PdfPages.svelte` | Uno por visor: registra nuestro contenedor como `Viewport` y dibuja las páginas con `Scroller`. `show(id)` cambia el documento a la vista |
| `PdfPage.svelte` | Una página: imagen de fondo (`RenderLayer`) y mosaico (`TilingLayer`) dentro de `Rotate`, y nuestras capas encima |
| `canvas.ts` | `PageCanvas`: la misma API de antes (zoom, modos, ir a página, coordenadas, marcas) sobre las capacidades de EmbedPDF |

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
- **Ctrl+rueda** la lleva `canvas.ts`: un paso de ratón es ×1,25, como antes. El trackpad da pasos
  más finos. La de EmbedPDF duplica el zoom en cada paso de ratón.
- **Pellizco** en pantallas táctiles: de EmbedPDF (`ZoomGestureWrapper`). Es nuevo.
- **Modos de vista:**
  - Continuo: estrategia vertical de EmbedPDF.
  - Página única y doble página son paginados: se ve una página o un par, y la rueda pasa de
    página en el borde. EmbedPDF no los trae; `embed.ts` añade al complemento de scroll una
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
- `selection.ts` dibuja la selección con nuestras marcas (`.sel-rect`) y muestra nuestra barra flotante
  (copiar, resaltar, subrayar, tachar, censurar, buscar, Google, explicar con IA). Con las
  herramientas resaltar, subrayar y tachar, al soltar se crea la anotación, como antes.
- Desde el paso 4, la selección da a las anotaciones y a la censura sus partes
  (`getFormattedSelection`), que se convierten en anotaciones o marcas de EmbedPDF.

**El texto de OCR:** las palabras las guarda Python (`entry.ocr`) y el visor las escribe en su
documento como texto invisible con el motor de la app (`writeOcrText`, en `lib/pdf-engine/page-ocr.ts`):
cada palabra ocupa su caja, también en páginas giradas, y se omiten las que tapan texto nativo (el
mismo criterio que la capa de texto). Al abrir una versión, las que da `viewer.document_url`; tras un
OCR, las nuevas, sin volver a abrir el documento (ver la etapa 3). El documento guardado no cambia.

**Cómo encaja con el resto del ratón:**
- Cada página va dentro de un `PagePointerProvider`, que pasa el ratón a la selección (y, desde el
  paso 4, a las anotaciones). Los eventos siguen subiendo al lienzo, donde escuchan las demás herramientas.
- Nuestras capas de marcas no reciben el ratón (`pointer-events: none`). La imagen y el mosaico de
  la página tampoco: EmbedPDF solo quita la selección de las anotaciones (y termina el texto libre)
  si el clic cae en la propia página.
- Con las herramientas de texto (seleccionar, resaltar, subrayar, tachar) el gestor de interacción
  está en el modo de texto; con las demás, en `viewer-tools`, donde la selección está apagada.
- EmbedPDF solo termina un arrastre con el `pointerup` de la página donde empezó. Si se suelta en
  otra página, entre páginas o fuera del lienzo, lo termina `selection.ts`.

**Coordenadas:** las de EmbedPDF son de la página sin girar; `selection.ts` las pasa a las de la página
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
- Tras una operación de página, un OCR o la censura la búsqueda se repite sobre el documento como
  queda (el visor lo cambia sin volver a abrirlo; si se está abriendo, espera a `canvas.loading`).
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
deshacer y rehacer). Se conservan nuestras herramientas, la paleta, la barra de propiedades y que
tras dibujar una forma se vuelve al puntero con ella seleccionada. Los sellos y las firmas tienen su
propia sección («Sellos y firmas»).

**Herramientas** (barra del lienzo):

| Grupo | Herramientas |
|---|---|
| Texto seleccionado | Resaltar, subrayar, tachar, subrayado ondulado, indicar texto omitido (marca de inserción con el texto que falta) y reemplazar (tacha lo seleccionado y guarda el texto nuevo, agrupados) |
| Formas | Rectángulo, círculo, línea, flecha, polilínea y polígono (clic en cada vértice, doble clic para terminar) |
| Trazos | Pluma, marcador (translúcido) y trazo fino |
| Texto e imagen | Texto libre; con clic derecho, llamada (texto con flecha) y nota; imagen (elige un archivo y se coloca con un clic) |

Las de texto seleccionado las crea `annotations.ts` (`markup`), como antes; las demás son las
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
- EmbedPDF las edita en su documento; Python no lo tiene (ver la etapa 4). Al guardar, el motor
  saca la copia (`saveCopy`, sin el texto del OCR), el visor la sube por el servidor local
  (`ByteServer.expect`, `POST`, `Host.upload_url`) y Python la escribe tal cual (ver «Guardar,
  extraer, propiedades e imprimir»).
- Los enlaces siguen bloqueados en EmbedPDF: son del documento.
- `viewer.annotations_changed` avisa del primer cambio: así Python sabe que hay cambios sin guardar
  (aviso al cerrar la pestaña o la app).
- Tras una operación de página, censura u OCR se reabre la versión de Python: el historial de
  deshacer empieza de nuevo (como antes tras cambiar páginas).

**Piezas:**

| Archivo | Qué hace |
|---|---|
| `palette.ts` | Colores y estilos (solo datos; también los valores iniciales de las herramientas en `embed.ts`) |
| `annotations.ts` | `Annotations`: estilo por visor, marcas de texto, crear/cambiar/borrar, deshacer, aviso de cambios y `sync` con Python |
| `editing.ts` | `AnnotationEditor`: barra de propiedades (color, grosor, letra, relleno, editar nota, traer al frente, enviar al fondo, duplicar, eliminar), teclado (Supr, Esc, Ctrl+D, flechas) y doble clic en una nota |
| `PdfPage.svelte` | `AnnotationLayer` de EmbedPDF dentro de cada página |
| `canvas.ts` | `ANNOTATION_TOOL`: herramienta de EmbedPDF de cada herramienta de dibujo (rectángulo → `square`, flecha → `lineArrow`, pluma y trazo fino → `ink`, texto → `freeText`, nota → `textComment`) |

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
  grupos (reemplazar texto) se rehacen enteros y se vuelven a enlazar. Un sello (también una
  imagen o una firma escrita) no lleva su dibujo en el objeto: antes de reordenar se exporta
  (`exportAnnotationAppearanceAsPdf`, un PDF de una página) y se recrea con él, como al colocarlo.
  Las demás anotaciones que ya traía el PDF, al rehacerse, toman la apariencia que les da EmbedPDF.

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

### Sellos y firmas (hechos): `plugin-stamp` y `plugin-signature`

Todos los sellos y las firmas se colocan igual: se elige en el panel «Sellos» (barra del lienzo:
**Sellos** o **Firma**) y el siguiente clic en la página lo coloca, con su vista previa bajo el
puntero; Esc cancela. Después se mueven y se redimensionan como las demás anotaciones. Los
estándar, los propios y las firmas escritas o desde imagen son anotaciones de sello (las firmas
dibujadas, de tinta) con su dibujo: un PDF de una página por sello, que EmbedPDF pega como
apariencia (`/AP`). Los **sellos de texto son texto libre** (`Annotations.textStamp`): se editan
como cualquier texto libre (doble clic) y se les cambia el color y el tamaño en la barra de
propiedades. Se guarda tal cual, como las demás anotaciones.

**Bibliotecas** (`stamps/library.svelte.ts`, una para toda la app, como el registro):

| Biblioteca | Qué tiene | Dónde vive |
|---|---|---|
| Estándar | Aprobado, Borrador, Confidencial, Firmar aquí… (17, en español) | El paquete `@embedpdf/default-stamps` (MIT), dentro de la app (`standard.ts`). Por defecto el complemento los descargaría de su CDN al arrancar: se desactiva (`manifests: []`) |
| De texto | Los sellos rápidos (CONFIDENCIAL, APROBADO…) y las leyendas guardadas | El servicio `legends`, el mismo almacén que Qt y Flet. En la página son texto libre; su miniatura se genera al vuelo (`stamp-pdf.ts`) en una biblioteca que solo vive en memoria |
| Propios | Los que crea el usuario desde una imagen (PNG, JPG, WebP, SVG) o desde anotaciones seleccionadas en la página (`createStampFromAnnotations`) | El servicio `stamps`: la biblioteca exportada por EmbedPDF (`~/.pdf_manager/stamps/custom.pdf` y `custom.json`) |

`stamp-pdf.ts` escribe a mano el PDF de un sello, sin PDFium ni Python: el de texto (la
miniatura), con texto vectorial en Helvetica Negrita (una de las 14 estándar, sin incrustar;
WinAnsi), marco del color y fondo blanco, como las leyendas de Qt; el de imagen, la imagen con su
transparencia (máscara `/SMask`); las SVG se dibujan antes en un lienzo. `textStampSize` da el
tamaño del sello de texto: lo usan la miniatura, la vista previa y el texto libre, así miden lo mismo.

**Firmas** (`stamps/signatures.svelte.ts`, `SignatureDialog.svelte`): firma e iniciales (opcional),
dibujadas, escritas o desde una imagen. Los paneles de dibujar y escribir son los de EmbedPDF
(`SignatureDrawPad`, `SignatureTypePad`); para escribir se usan letras manuscritas que trae Windows
(Segoe Script, Ink Free, Lucida Handwriting) en vez de su «Dancing Script», que habría que
descargar. La imagen se pasa a PNG antes (PDFium no pinta una SVG). Es una firma **visual** (trazo
o imagen), sin certificado digital. El usuario decide si cada firma se guarda en el equipo para
reutilizarla (`~/.pdf_manager/stamps/signatures.json`, formato de `serializeEntries`); si no, dura
mientras la app esté abierta.

**Herramientas «colocar»** (`canvas.ts`): con `TOOLS.PLACE` el panel pone la herramienta del
lienzo en «colocar» y EmbedPDF activa la suya (`rubberStamp`, `signatureStamp` o `signatureInk`); al
crear el sello se vuelve al puntero con él seleccionado (`_created`) y, si EmbedPDF deja la
herramienta sin crear nada, se vuelve a seleccionar texto (`onActiveToolChange`). Los sellos de
texto usan `TOOLS.PLACE_TEXT`, sin herramienta de EmbedPDF: `StampsPanel.svelte` dibuja la vista
previa bajo el puntero (una marca de la página con el aspecto del sello) y el clic crea el texto
libre (en la fase de captura, para no seleccionar la anotación que haya debajo).

Los paneles de EmbedPDF avisan (`onResult`) desde sus propios efectos: si el aviso lee el estado
que escribe, Svelte vuelve a ejecutar el efecto sin fin. Por eso `SignatureDialog.set` escribe con
`untrack`.

**Comprobado** con ratón real por CDP (`stamps_e2e`, 30 comprobaciones): las tres bibliotecas con
sus miniaturas; colocar un sello estándar; el de texto con su vista previa, editarlo con doble
clic (el texto nuevo llega al PDF); enviar un sello al fondo y traerlo al frente (conserva su
dibujo); Esc cancela; sellos propios desde PNG
(con su margen transparente) y SVG, guardados por Python; desde un rectángulo seleccionado;
quitarlos; firma dibujada (guardada) y escrita (solo en la sesión); y Ctrl+S guarda sellos y firmas
con su dibujo.

### Operaciones de página (las hace EmbedPDF, con deshacer)

Girar, insertar en blanco, duplicar, borrar y mover se hacen en el documento abierto en EmbedPDF,
sin volver a abrirlo, y se pueden deshacer. Cómo funciona: «EmbedPDF, dueño del documento del visor».

**Un solo Ctrl+Z** (y el botón «Deshacer»): primero deshace lo de EmbedPDF (anotaciones) y, cuando
no queda nada, la última operación de página. Tras una operación de página el historial de EmbedPDF
empieza de nuevo, así que el orden se respeta: lo hecho después de girar se deshace antes que el giro.
Lo que se pierde: lo que quedaba por rehacer en las anotaciones al hacer una operación de página.

### Censura (hecha): EmbedPDF marca, Python aplica

Complemento `redaction` de EmbedPDF en **modo anotación**: cada marca pendiente es una anotación
`Redact`. Se ve con borde rojo y, al pasar el ratón, con el relleno que tendrá; se selecciona, se
mueve, se redimensiona (las de área), se borra (Supr) y se deshace (Ctrl+Z) como las demás
anotaciones. Antes, la vista previa era una capa nuestra que no se podía tocar.

**Quién hace qué:**
- **Marcas** (`tools/viewer/redact/redaction.ts`, `RedactionMarks`). Las ponen:
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
- **Aplicar** (`redact/apply.ts`): el motor de EmbedPDF las aplica en el documento del visor
  (`applyAllRedactions`, sin volver a abrirlo): borra lo de debajo (texto, también el invisible del
  OCR y el de dentro de Form XObjects; píxeles de las imágenes; dibujos), pinta el recuadro (`/RO`) y
  quita la marca. Las páginas censuradas suben de revisión (cambian de clave: `PageEditor.contentChanged`)
  y `redact.apply` le dice a Python cuáles, con sus marcas: borra las palabras de OCR que tapaban.
- **Comprobado** (`tests/test_pdf.py`, con el motor real, tarea `redact` de `engine_task.mjs`, la misma
  función que el visor): en el archivo guardado no queda el texto en ningún stream, en la imagen no queda ni un píxel de la zona tapada (fuera de ella sigue intacta), el
  recuadro sale del color elegido y en su sitio en los cuatro giros, y un PDF cifrado sigue cifrado.

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
selección de texto está apagado). Mientras se marca, `selection.ts` no muestra su barra: la selección
es del complemento de censura.

**Comprobado** (scratchpad `redact_e2e.py`, 17 comprobaciones, también en modo desarrollo): término
(con la página girada), patrón, borrar una marca y deshacer, Ctrl+Z del patrón de una vez, marcar un
área y un texto, Esc, selección enviada, color, aplicar, y la búsqueda ya no encuentra lo censurado.
En Python, las pruebas `test_redact_*` (las marcas las pone la prueba en la copia, como el visor).

**Retirado:** `redact.add_term`, `add_region`, `remove_term` y `clear` (la lista son las marcas),
`ViewerService.apply_redactions`, `pdf_core.redaction.apply` y la vista previa `.redact-preview`.

### Imprimir (hecho): el diálogo de WebView2 con el PDF

Ctrl+P (o «Imprimir documento» en el menú ⋮) abre directamente el diálogo de impresión de
WebView2, el de Edge: vista previa, impresora, copias, páginas (todas, pares, impares o un rango),
orientación, color, márgenes, escala, páginas por hoja y doble cara. `document/print.ts` abre en un
iframe oculto la copia del PDF de EmbedPDF con las anotaciones al día (`DocumentCopy.pdf`, la misma
que se guarda, sin cifrar) y llama a `print()` de su visor de PDF. Se imprime el PDF tal cual:
vectorial (el texto sale nítido) y sin dibujar antes cada página como imagen (con el PDF de 43 MB y
120 páginas el diálogo se abre en menos de un segundo). La copia va siempre sin cifrar, así que el
visor de PDF no pide contraseña.

Antes había un diálogo propio (rango, orden inverso, orientación por página, color, escala y vista
previa) que dibujaba las hojas con PDFium a 150 ppp y después abría el diálogo del navegador: dos
diálogos seguidos. Del propio solo se pierden el orden inverso y la orientación automática página
por página; lo demás lo trae el de WebView2.

El complemento `print` de EmbedPDF hace lo mismo (el PDF en un iframe oculto); no se usa porque
`print.ts` son unas líneas y usa la copia que ya saca el motor para guardar.

**Comprobado** (`annot_e2e`, sustituyendo la ventana del iframe: el `print()` del visor de PDF no
se puede cambiar): Ctrl+P abre el diálogo con un PDF con las tres páginas y sus anotaciones. Y en la
app aislada, con captura de su ventana (`PrintWindow`), el diálogo real con la vista previa, también
con el PDF de 120 páginas.

**Retirado:** `PrintDialog.svelte`, `canvas.pageImages`, la capa `#print-root` y sus estilos de
impresión, y `viewer.print_selection` (Python; `pdf_core.page_ranges` sigue para el OCR por lotes).

## EmbedPDF, dueño del documento del visor

Decidido el 2026-11-10. El documento del visor estaba dos veces (en Python y en EmbedPDF; en el
navegador, tres, con la copia de `/files`) y cada operación de página lo serializaba entero en Python
y lo volvía a abrir en EmbedPDF. Ahora el dueño es EmbedPDF, por etapas que dejan la app funcionando:

| Etapa | Qué pasa a EmbedPDF | Estado |
|---|---|---|
| 1 | Operaciones de página y su deshacer | Hecha |
| 2 | Guardar, guardar como, extraer una página, propiedades e imprimir (Python solo escribe los bytes) | Hecha |
| 3 | El texto del OCR y la orientación (Python recibe imágenes de página) | Hecha |
| 4 | Quitar el documento del visor de Python (en el navegador, sin copia en `/files`) | Hecha, salvo la copia de `/files` |
| 5 | La IA lee el texto a través de EmbedPDF | Pendiente |

### El motor de la app (`lib/pdf-engine/`)

El motor de EmbedPDF no sabe cambiar las páginas de un documento abierto, pero su PDFium trae todas
las funciones. `createPdfiumEngine` crea su worker desde un `blob:` y no deja añadirle métodos, así que
la app tiene el suyo, con el mismo protocolo (su `PdfEngine` funciona igual encima):

| Archivo | Qué hace |
|---|---|
| `native.ts` | `AppNative`, el `PdfiumNative` de EmbedPDF con lo que le falta: girar (en el archivo), mover, borrar, insertar en blanco, duplicar y guardar una página aparte para devolverla; las copias del documento (`saveCopy`, `extractCopy`, sin el texto del OCR y, para imprimir, sin cifrar), la versión del PDF y la copia rápida del PDF desde el wasm (`saveDocument`); y lo del OCR (`pageFacts`, `pageImage`, `writeOcrText`). Lo prueba también Python con el motor real (`tests/engine_task.mjs`, tareas `pages`, `copy`, `extract`, `facts`, `ocr-write`, `ocr-facts` y `ocr-image`) |
| `page-ocr.ts` | Lo que necesita el OCR: leer una página (su texto sin el del OCR, líneas, sentido del texto y dónde tiene imágenes), dibujarla o un trozo de ella en RGB, y escribir y quitar el texto invisible del OCR (marca `ExtraerPDFsOCR`). Trabaja con páginas abiertas aparte, sin girar: las de EmbedPDF están «normalizadas» |
| `pdfium.ts` | Las funciones de PDFium que se llaman directamente y las partes privadas de `PdfiumNative` que se usan |
| `worker.ts` | El worker: atiende las llamadas por el nombre del método, como el de EmbedPDF. Los PDF y las imágenes que devuelve pasan a la ventana sin copiarlos (se transfieren) |
| `index.ts` | `createAppEngine`: el worker, el ejecutor que le pasa las llamadas y las operaciones nuevas con sus tipos: `PageStructure` (páginas), `DocumentCopies` (copias) y `PageReading` (OCR) |
| `encoder.ts`, `encoder-worker.ts` | Codifican en workers las imágenes que dibuja el motor (EmbedPDF no publica el suyo) |
| `protocol.ts` | Los mensajes entre la ventana y el worker |

Usa partes privadas de `PdfiumNative` 2.15.1 (la caché de documentos, el módulo de PDFium; en
`pdfium.ts`): revisarlas al actualizar EmbedPDF. Las pruebas cargan estos archivos en Node, que solo
quita los tipos: nada de sintaxis que haya que compilar (como los parámetros `private` de un constructor). Al cambiar el orden de las páginas hay que vaciar su caché de páginas, que va
por número de página (el `deletePage` de EmbedPDF no lo hace).

### Cómo se cambian las páginas

- `document/pages.ts` (`PageEditor`) hace cada operación en el motor, lleva las claves de página, el
  deshacer y rehacer (30 pasos; la página borrada se guarda aparte con sus anotaciones) y sabe si la
  estructura es la guardada. `document/operations.ts` decide a qué página ir, como antes.
- `canvas.showPages` muestra la lista nueva sin volver a abrir el documento (`showPageList` en
  `embed.ts`): la acción `SET_PAGES` del núcleo, `REFRESH_PAGES` para redibujar, reagrupar las páginas
  (doble página), recolocarlas y volver a leer las anotaciones. Cada página se vuelve a montar al
  cambiar su contenido (`{#key}` en `PdfPages.svelte`).
- **Claves de página** `uid:giro:revisión`: el `uid` lo da el visor a las páginas nuevas y sigue a
  cada página aunque cambie de sitio; la revisión sube al censurarla. Con la clave Python guarda las
  palabras del OCR y el texto de la página, que vuelven si se deshace el giro o el borrado de su página.
- **Python recibe la estructura** (las claves, `viewer.set_pages`) antes de lo que lee el texto
  (`syncText` en `Viewer.svelte`, en la cola del documento; ver la etapa 4), y al guardar, con la
  copia que se escribe.
- **Orientación automática:** el visor sabe cuántos grados girar (por el sentido del texto o, en un
  escaneo, `ocr.orientation`: ver la etapa 3) y gira la página; se deshace como cualquier giro.
- **Cambios sin guardar:** anotaciones o censura (lo dice Python, `annotated` y `redacted`) o una
  estructura distinta de la guardada (`PageEditor.changedWith`). Deshacerlo todo vuelve a «sin cambios».

**Medido** (PDF de 47 MB y 250 páginas, versión web): mover una página tarda 38–54 ms desde el clic
en el menú; antes, solo serializar, transferir y volver a abrir costaba 330–550 ms, sin contar volver
a dibujar. Y ya no se crea una copia entera del PDF en cada operación.

**Comprobado:** en Python, `test_engine_*` (`tests/test_pdf.py`, el motor real) y
`test_viewer_takes_the_pages_from_the_viewer_copy` y `test_viewer_keeps_ocr_words_while_their_page_moves_or_turns`;
en la app, scratchpad `pages_e2e.py` (16 comprobaciones: cada operación, la nota de una página
duplicada, deshacer y rehacer, y las propiedades al día, sin volver a abrir el documento).

### Guardar, extraer, propiedades e imprimir (etapa 2)

Lo que sale del visor lo saca el motor de la app, y Python solo escribe los bytes:

- **`document/copy.ts` (`DocumentCopy`)** es la copia del documento que sale del visor: `pdf()` (el
  PDF entero), `page(i)` (una página como PDF nuevo) y `upload()` (subirla a Python, con la clave de
  cada página); `send()` sube cualquier dato. Antes estaba dentro de `annotations.ts`.
- **Sin el texto del OCR:** el motor lo quita por su marca (`ExtraerPDFsOCR`) en una copia abierta
  aparte, solo de las páginas que lo llevan; el documento a la vista lo conserva para seleccionar y
  buscar. Cuáles lo llevan lo apunta el lienzo al escribirlo (`canvas.ocrPages`, por `uid`), y la
  copia de una página duplicada también lo lleva (`PageEditor.duplicate`). Antes lo quitaba Python
  al recibir la copia, y no lo quitaba de las páginas duplicadas: el texto del OCR de una copia
  acababa en el archivo.
- **Guardar y «Guardar como»** (`viewer.save` / `save_as(id, url, keys)`): Python abre la copia (así
  nunca escribe una que no se pueda leer), la escribe tal cual en el archivo y la suelta. Antes
  volvía a generar el PDF entero. Un PDF cifrado sigue cifrado: la copia lo está.
- **Extraer página** (`viewer.extract_page(id, página, url)`): el motor saca la página con sus
  anotaciones (sin cifrar, como antes) y Python la escribe donde elija el usuario. Ya no hace falta
  pasar antes el documento entero a Python.
- **Propiedades** (`document/properties.ts`): metadatos, versión y cifrado los da el motor, las
  páginas las sabe el visor y de Python solo viene el tamaño del archivo (`viewer.file_size`). Antes
  había que pasarle el documento entero para abrir el diálogo. Las fechas salen legibles (antes,
  `D:20240101…`).
- **Imprimir:** la misma copia, sin cifrar si lo está (`pdf({ decrypt: true })`, el motor quita el
  cifrado en la copia aparte). `viewer.print_url` ya no existe.
- **Exportar texto e imágenes** siguen en Python, con el documento al día (`sync`): el texto pasa a
  EmbedPDF con la IA (etapa 5).

**La copia rápida.** El `saveDocument` de `PdfiumNative` copiaba el PDF desde la memoria del wasm byte
a byte (`getValue` por cada byte); `AppNative` lo copia de una vez (`HEAPU8.slice`). Lo usan todas las
copias: guardar, imprimir, `sync`, las tareas de `engine-tasks.ts` y extraer páginas.

**Medido** (PDF de 47 MB y 250 páginas, versión web, scratchpad `perf_save.py`):

| Qué | Antes | Ahora |
|---|---|---|
| Copia del PDF en el motor (también en cada `sync`) | 473–554 ms | 48–66 ms |
| Python vuelve a generar el PDF al guardar (Pyodide) | 72–95 ms | no se hace |
| Ctrl+S hasta tener el archivo descargado | — | 559–730 ms |
| Abrir «Propiedades» con cambios | pasar el documento entero a Python | sin pasarlo |

En Node, la misma copia: 887 ms → 78 ms; en Python de escritorio, volver a generar el PDF costaba
172 ms y quitar el texto del OCR de todas las páginas, 156 ms.

**Comprobado:** en Python, `test_engine_copy_*`, `test_engine_extracts_*` y
`test_engine_tells_the_pdf_version_and_encryption` (`tests/test_pdf.py`, el motor real) y
`test_viewer_save_writes_the_viewer_copy_as_is` (`tests/test_app_backend.py`, que además hace de visor
en todas las pruebas de guardar); en la app, scratchpad `save_e2e.py` (16 comprobaciones: OCR,
duplicar y girar, guardar sin el texto del OCR ni volver a abrir el documento, propiedades, extraer e
imprimir).

### El OCR y la orientación (etapa 3)

Python ya no lee el documento para reconocerlo: el motor de la app dibuja lo que hay que reconocer y
escribe el texto reconocido en el documento a la vista.

- **`ocr/recognize.ts` (`PageRecognizer`)** hace el OCR de una página (`page`), de un recorte
  (`area`) y la orientación (`orientation`). Lo usan el panel del OCR, el lote y «Corregir
  orientación»:
  1. el motor lee la página (`pageFacts`): cuántos caracteres y líneas tiene sin contar el texto del
     OCR, el sentido del texto y dónde tiene imágenes;
  2. dibuja lo que se reconoce (`pageImage`, RGB): las imágenes de la página o, si no tiene, la página
     entera (con las mismas resoluciones que usa Python con los archivos, en `processor.py`);
  3. lo sube (`viewer.upload_url`, todas las imágenes en un envío) y Python lo reconoce
     (`ocr.page(id, página, url, regiones, hechos)` u `ocr.area(id, página, url, región)`): guarda
     las palabras para su capa de texto y las devuelve (`words`);
  4. el motor las escribe en el documento como texto invisible (`canvas.writeOcrText`: el de la
     página sustituye al que tenía; el de un recorte se suma) y EmbedPDF vuelve a leer esa página
     (`refreshPageText`, la acción `REFRESH_PAGES` del núcleo: la selección y el dibujo; la búsqueda
     la vuelve a lanzar el visor).
- **Antes:** Python dibujaba la página de su copia y, tras cada OCR, el visor volvía a pedir el
  documento entero (Python lo generaba con el texto invisible) y lo abría otra vez en EmbedPDF.
- **Al abrir una versión** (al principio y tras censurar), `document_url` da el PDF sin el texto del
  OCR y las palabras de cada página (`ocr: [{index, words}]`), y el lienzo las escribe antes de
  mostrarla. Python ya no escribe texto invisible (`Page.add_invisible_text` y `embed_ocr_words` se
  quitaron): lo escribe y lo quita solo el motor.
- **Orientación:** si la página tiene texto (30 caracteres o un sentido distinto del normal), la dice
  el sentido de su texto, en el visor y sin llamar a Python. Si es un escaneo, el motor la dibuja a
  0,8 px por punto y la sonda, y Python decide con el clasificador y, si duda, con el OCR en las
  cuatro orientaciones (`ocr.orientation(url, imágenes)`, `OCRProcessor.image_correction`).
- **Python tiene que tener el texto de la página** para el que devuelve (`ocr.page` da el de la
  página entera, con el nativo) y comprobar que la página sigue siendo la misma: el panel llama
  antes a `syncText([página])`, que no sube nada si ya lo tiene.
- **Límite que sigue:** Python guarda las palabras por la clave de la página, y la copia de una
  página duplicada tiene otra. En el visor la copia lleva el texto (lo copia el motor con la página) y
  no llega al archivo, pero el asistente IA y exportar texto no lo ven. Lo resuelve la etapa 5.

**Medido** (PDF de 47 MB y 250 páginas, versión web, scratchpad `perf_ocr.py`):

| Qué | Antes | Ahora |
|---|---|---|
| Tras cada OCR, volver a abrir el documento entero (Python lo genera con el texto, EmbedPDF lo abre) | 269–318 ms | no se hace |
| El motor lee la página / la dibuja a 2 px por punto (1190 × 1684) | — | 1–9 ms / 25–30 ms |
| «Procesar Página Actual» de punta a punta, con el modelo ya cargado (0,7 s de inferencia) | — | 759–873 ms |

Y Python ya no dibuja la página de su copia del documento.

**Comprobado:** en Python, `test_engine_writes_ocr_words_on_their_rectangle` (los cuatro giros, y la
página se ve igual), `test_engine_ocr_words_replace_the_previous_ones_and_skip_native_text`,
`test_engine_reads_page_facts_without_the_ocr_text` y `test_engine_draws_the_page_as_seen_for_the_ocr`
(`tests/test_pdf.py`, el motor real); `test_ocr_words_join_the_text_layer_search_and_export`,
`test_ocr_batch_pages_and_orientation` y `test_document_url_gives_the_ocr_words_for_the_viewer_to_write`
(`tests/test_app_backend.py`, que hace de visor con imágenes dibujadas por Python). En la app,
scratchpad `ocr_e2e.py` (19 comprobaciones, con los modelos reales: recorte y página sin volver a abrir
el documento, búsqueda, orientación de una página con texto y de un escaneo de lado, lote, guardar
sin el texto del OCR y censurar, que conserva el resto del texto del OCR).

### Python sin el documento del visor (etapa 4)

Python ya no tiene abierto el PDF del visor (antes, `entry.doc`, que se cambiaba por cada copia que
subía el visor). Lo lee una vez al abrirlo (contraseña, tamaños, índice, metadatos, permisos) y lo
suelta. Lo que necesita de él le llega del visor:

- **El texto de las páginas** (`document/text.ts`, `DocumentText.sync`): el visor le da la clave de
  cada página (`viewer.set_pages`), Python contesta qué páginas no tiene (`missing`) y el visor le da
  solo el texto de esas: el motor lo extrae (`pageTexts`, `lib/pdf-engine/page-text.ts`: cada carácter
  con su caja holgada y su línea, sin el texto del OCR, igual que lo lee Python de un PDF) y lo sube en
  binario (`viewer.add_texts`, 24 bytes por carácter). Python lo guarda así, por clave
  (`PackedPageText`), y lo desempaqueta al usarlo (`PageText`). El texto de una página no cambia con
  sus anotaciones ni al moverla, así que cada versión de una página se extrae una vez.
- **Con ese texto** trabajan la capa de texto en orden de lectura (`text_layer.py`: asistente IA,
  panel del OCR, exportar texto) y la búsqueda de la censura (`redaction.find_in_page`), que ahora
  reciben un `pdf_core.pdf.PageText` (lo da también `Page.page_text` con un PDF abierto en Python).
- **Lo pide** lo que lee el texto: el asistente IA, la búsqueda de la censura y exportar texto, de
  todas las páginas (`syncText()`), y el panel del OCR, de la página que muestra (`syncText([i])`).
- **La censura** la aplica el visor (ver «Censura»); Python solo borra las palabras del OCR tapadas
  (`ViewerService.redaction_applied`). Ya no se vuelve a abrir el documento.
- **Guardar** escribe la copia que sube el visor; los permisos los comprueba Python al abrir el
  archivo (`can_save`). **Exportar imágenes** recibe una copia del visor, que Python abre, usa y
  suelta (`viewer.export_images(id, url)`).
- **`document_url`** sirve el archivo tal como está en disco, con sus claves (`file_keys`): solo se
  usa al abrirlo.
- **El estado** que devuelve Python (guardar, censurar) ya no lleva las páginas (`DocumentState` en
  `lib/types.ts`): las lleva el visor. Python lleva las claves y sabe con ellas si la estructura es
  la guardada.

**Queda la copia de `/files` en el navegador:** el archivo que se abre se copia al sistema de archivos
de Pyodide, donde lo leen `viewer.open` y `document_url` y donde Python escribe al guardar (y la
ventana lo pasa al archivo real). Quitarla obliga a que el visor abra el archivo sin Python y a que
guardar no pase por `/files`: está por decidir.

**Medido** (PDF de 47 MB y 250 páginas, versión web, scratchpad `perf_text.py`):

| Qué | Tiempo |
|---|---|
| El motor extrae el texto de las 250 páginas (935.000 caracteres, 22 MB empaquetado), la primera vez / después | 4,0 s / 1,1–1,2 s |
| Subirlo a Python (`viewer.add_texts`) | 26–34 ms |
| «Generar Resumen» del asistente (modo básico) con el texto ya en Python | 93–105 ms |

Python de escritorio tardaba 13,2–13,7 s en leer ese mismo texto de su copia con `pypdfium2`. El
texto de una página para el panel del OCR se extrae en unos milisegundos. Dos cosas lo hacen rápido:
el motor lee el texto de cada página de una vez (`FPDFText_GetText`) y las cajas directamente de su
memoria, y no mira de qué objeto es cada carácter si la página no tiene texto del OCR; Python no
desempaqueta un objeto por carácter para leer el texto ni para buscar en él (`PackedPageText.text`
y `text_map`), solo para la capa en orden de lectura de una página.

**Comprobado:** en Python, `test_engine_gives_python_the_same_page_text_without_the_ocr` (los cuatro
giros: mismo texto, mismas líneas y cajas a menos de 1 pt, y la misma capa de texto) y
`test_engine_page_texts_come_in_the_order_asked` (`tests/test_pdf.py`); en `tests/test_app_backend.py`
todas las pruebas del visor, el OCR, la censura y la IA hacen de visor con `FakeViewer` (su documento,
sus claves y el texto en el formato del motor). En la app, scratchpad `ocr_e2e.py`, `save_e2e.py`,
`pages_e2e.py` y `web_tools_e2e.py` (que censura desde el panel).

## Un solo motor

Todo usa PDFium: el de EmbedPDF en la ventana y `pypdfium2` en Python (`pdf_core/pdf.py`). Antes Python
usaba PyMuPDF, con licencia AGPL, y había dos motores. Se retiró en la 0.1.29-web.

**Reparto:**
- **El documento del visor es de EmbedPDF**: lo edita (anotaciones, páginas, censura) y saca sus
  copias. Python no lo tiene abierto: recibe el texto de sus páginas y, al guardar, la copia que
  escribe (ver la etapa 4). Los archivos de las demás herramientas (Unir, Extraer, Seguridad…) sí los
  abre Python con `pypdfium2`, siempre a memoria: así se puede sobrescribir el archivo abierto.
- **Lo que el PDFium normal no sabe hacer** lo hace el de EmbedPDF, que tiene funciones propias:

  | Tarea (`lib/engine-tasks.ts`) | Quién la pide | Función de EmbedPDF |
  |---|---|---|
  | `encrypt` | `security.protect` | `setDocumentEncryption` (AES-256, R6) |
  | `outline` | `merge.merge` (marcadores) | `setBookmarks` |

  `Host.run_engine(tarea, pdf, args)` comparte el PDF por el servidor local, emite `engine:task` y espera
  a que la ventana suba el resultado y llame a `app.engine_done`. La ventana abre un documento propio
  en el motor, sin tocar los del visor.

**Identidad de las páginas.** PDFium no da el número de objeto de una página, así que cada página
lleva un identificador (`Document.uids` al abrir el archivo: 1, 2, 3…). La clave de página es
`id:rotación:revisión`. Después los da el visor, que es quien añade, mueve y censura las páginas.

**PDF cifrados.** El visor abre el PDF cifrado con su contraseña (`document_url` la devuelve), y por eso
su copia conserva el cifrado y las dos contraseñas sin conocer la de propietario. Los permisos no se
aplican en el visor (`enforceDocumentPermissions: false`): los comprueba Python al guardar. Para imprimir,
el motor saca la copia sin cifrar (`saveCopy` con `decrypt`), o el diálogo pediría la contraseña. Un PDF
descifrado por PDFium (esa copia y «Desbloquear») ya no está cifrado, pero conserva sin usar el
diccionario de cifrado antiguo: buscar el texto `/Encrypt` en el archivo da un falso positivo.

**Texto del OCR.** El visor escribe las palabras reconocidas como texto invisible en su documento,
con la marca de contenido `ExtraerPDFsOCR` (`lib/pdf-engine/page-ocr.ts`). El motor del visor las
quita por esa marca de las copias que salen de él (`AppNative.saveCopy`), así el texto reconocido no
pasa al archivo ni a Python.

**Diferencias con PDFium que importan:**
- Las cajas de los caracteres pueden ser las del glifo o las holgadas, con la altura de la fuente
  (`Char.rect` y `Char.box`). Para buscar, censurar y ordenar se usan las holgadas: con las del glifo las
  letras altas y bajas de una línea quedan a distinta altura y el orden de lectura las separa.
- PDFium ordena el texto de una página girada como se ve; `Page.chars` lo lee con el giro a cero para
  que se lea en su sentido original.
- Las marcas y anotaciones van en coordenadas de la página sin girar porque la app abre los documentos
  con `normalizeRotation` (también en `engine-tasks.ts`).
- PDFium guarda el archivo entero pero no recomprime los streams: «Optimizar PDF» desapareció de Unir.

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
- **Girar sin recargar** (2026-10-30): antes cada giro mandaba y cargaba otra vez el documento
  entero (en EmbedPDF, tres copias del PDF a la vez hasta que se recogían) y crecía ~45 MB por giro.
  Desde el 2026-11-10 todas las operaciones de página se hacen así, en el documento abierto (ver
  «EmbedPDF, dueño del documento del visor»).
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
  `tiling`, `interaction-manager`, `selection`, `search`, `annotation`, `history`, `redaction`,
  `stamp` y `signature` (`export` se quitó: las copias las saca el motor de la app);
- `@embedpdf/default-stamps` 0.0.1 (MIT): los sellos estándar, con su manifiesto en español.

Y `svelte` fijado en 5.51.0 (ver «Anotaciones y sellos»).

Las miniaturas salen de `render` (`canvas.thumbnails`), no del complemento `thumbnail`, que se quitó:
el panel lateral ya tiene su propia lista virtual y sus tarjetas.

La interfaz compilada crece unos 5 MB: `pdfium.wasm` (4,6 MB) y el *worker* del motor (0,33 MB,
`lib/pdf-engine`; el de EmbedPDF ocupaba 0,7 MB). `@embedpdf/engines` no declara que sus módulos no
tienen efectos al importarlos: `vite.config.ts` se lo indica, o la ventana cargaría también su motor
PDFium entero (unos 140 KB), que solo usa el worker.

## Fallos de EmbedPDF que se esquivan

- **Mosaicos repetidos (`plugin-tiling` 2.15.1):** al volver a un zoom antes de que acaben los mosaicos del otro, crea
  unos con el mismo id que los de respaldo. La lista de Svelte falla con `each_key_duplicate` y el visor deja de
  responder. `ViewerTilingPackage` (`canvas/embed.ts`) los quita; hay que revisarlo al actualizar EmbedPDF.

Al cambiar las páginas de un documento abierto (operaciones de página), que EmbedPDF 2.15.1 no contempla:

- **`SET_PAGES` sin atender (`core`):** el núcleo declara la acción, pero su reductor no la procesa.
  `acceptPageLists` (`embed.ts`) envuelve el reductor del núcleo para que la atienda.
- **`SET_ANNOTATIONS` pierde anotaciones (`plugin-annotation`):** al recargarlas borra las que antes
  estaban en el mismo número de página, aunque acabe de ponerlas en otra; la capa fallaba con
  `Cannot read properties of undefined (reading 'object')`. `ViewerAnnotationPackage` la sustituye.
- **Imágenes de las anotaciones por número de página (`plugin-annotation`):** su caché y la capa de cada
  página no se vuelven a pedir si solo cambia el contenido; la nota de una página duplicada no se veía.
  Se vacía la caché (`showPageList`) y la página se vuelve a montar (`{#key}` en `PdfPages.svelte`).
- **Agrupación de páginas (`plugin-spread`):** solo se calcula al abrir; `showPageList` la vuelve a pedir.
- **Anotaciones de una copia con el mismo `/NM`:** EmbedPDF identifica cada anotación por él; al
  duplicar una página, `AppNative` les da uno nuevo.
- **El giro de una página cargada vale 0:** con la rotación normalizada, `FPDFPage_GetRotation` no da el
  giro real; `AppNative` lo lee del diccionario de la página (`EPDF_GetPageRotationByIndex`).
- **`extractText` de una página vacía** devuelve caracteres sin sentido (en el motor de EmbedPDF).

Al sacar copias del documento:

- **Copia lenta (`PdfiumNative.saveDocument`):** copia el PDF desde el wasm byte a byte; con 47 MB,
  medio segundo en el navegador. `AppNative` lo sustituye por una copia de una vez.
