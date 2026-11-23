# Imágenes en el visor

Cómo funcionan «Imágenes a PDF», insertar y ajustar páginas desde imágenes y exportar las páginas
como imágenes. La guía de uso está en la Ayuda de la app
([06_IMAGENES A PDF.md](../../src/assets/ayuda/06_IMAGENES%20A%20PDF.md)).

## Resumen

- **El PDF lo escribe la ventana**, en TypeScript ([`lib/images/images.ts`](../../app/ui/src/lib/images/images.ts)
  sobre [`lib/pdf-writer.ts`](../../app/ui/src/lib/pdf-writer.ts)). Funciona igual en el escritorio y
  en el navegador, y no necesita Pillow, PDFium ni pasar las imágenes por Python.
- **La imagen es contenido fijo de la página**, no una anotación ni un sello. El PDF se ve igual en
  cualquier lector. Para cambiar cómo encaja se rehace la página con el diálogo («Ajustar imagen…»).
  Se descartó usar sellos de EmbedPDF: se pueden mover sin querer, y aplanarlos al guardar añade un
  paso que puede fallar.
- **Python solo guarda y escribe**: abre el PDF nuevo como documento sin archivo (`viewer.create`) y
  escribe lo que le pasa la ventana (guardar, exportar).

## De dónde llegan las imágenes

| Entrada | Recorrido |
|---|---|
| Tarjeta de Inicio y menú «Imágenes a PDF…» | `shell.imagesToPdf()` → `<input type="file">` de la ventana ([`pick.ts`](../../app/ui/src/lib/images/pick.ts) `pickImageFiles`) |
| «Abrir» (Ctrl+O) | `documents.open_dialog` → `host.pick_documents()` (filtro «PDF e imágenes»: `app/host.py` `DOCUMENT_TYPES`; en el navegador, `files.ts` `pickPdfs(…, images)`) → `documents.open_many` |
| Arrastrar a la ventana | escritorio: `WebviewHost._on_drop` → `documents.open_many`; navegador: `files.ts` `droppedPdfs` → `open_files` → `documents.open_many` |
| «Abrir con» / otra instancia | `documents.open_many` |

`DocumentService.open_many` abre cada PDF como siempre (`document:open`) y manda **todas las
imágenes juntas** en un evento `images:open` `{paths}`. La shell (`shell.openImagePaths`) lee cada
una con `documents.image_url(path)`, que devuelve una URL de un solo uso de `host.file_url`: el
servidor de bytes en el escritorio y el archivo de la ventana en el navegador. Las extensiones
aceptadas están en `IMAGE_SUFFIXES` (`app/backend/services/documents.py`), en `files.ts` y en
`pick.ts`; una prueba comprueba que coinciden.

## El diálogo

[`ImagesDialog.svelte`](../../app/ui/src/lib/images/ImagesDialog.svelte) tiene tres modos:

| `mode` | Para qué | Qué muestra |
|---|---|---|
| `create` | Documento nuevo (Inicio, Abrir, arrastrar) | Ajustes generales, cuadrícula de páginas, vista grande y ajustes por página |
| `insert` | «Insertar páginas desde imágenes» en el visor | Igual; las páginas van detrás de `after` |
| `adjust` | «Ajustar imagen de la página» | Ajustes generales, la vista grande y el giro (sin cuadrícula ni orientación por página) |

- **Ajustes generales** (`PageOptions`): `paper`, `orientation` (`auto` | `portrait` | `landscape`),
  `margin` y `fit` (`contain` | `cover`). Se recuerdan en `localStorage` (`images-pdf-options`,
  `pick.ts`); si el almacenamiento falla, se usan los de siempre.
- **Cada página** (`Item`) lleva su giro y su orientación: `global` (la de todas) o una a mano.
  `pageOptions(item)` combina las dos. Cada página del resultado lleva sus propias `options`
  (`ImagePage`), así que la orientación a mano llega al PDF y a «Ajustar».
- **Vista previa:** la acción `use:sheet` dibuja cada hoja en un `<canvas>` con el mismo `layout()`
  que escribe el PDF, así que lo que se ve es lo que sale. Se redibuja al cambiar los ajustes.
- Devuelve `{ pages, pdf }`. Las imágenes que se quitan o se cancelan se sueltan (`releaseImages`,
  revoca sus URL `blob:`). Las que se usan las guarda el visor para «Ajustar».

## El PDF de las imágenes

`imagesPdf(pages)` escribe una página por imagen:

- **Maqueta** (`layout(ancho, alto, options)`):
  - **Hoja:**
    - La da el tamaño de papel y la orientación: `auto` es horizontal si la imagen girada es más ancha que alta.
    - Con `image`, la hoja tiene la forma de la imagen y su lado mayor mide como el de un A4.
  - **Dónde va la imagen:**
    - Encajada o rellenando el área dentro del margen.
    - Lo que sobresale se recorta (`re W n`).
- **JPG:** van tal cual (`/DCTDecode`), sin recomprimir.
  - `readJpeg` lee de la cabecera el tamaño, los componentes y la orientación EXIF.
  - La orientación y el giro del usuario se aplican en la matriz de dibujo (`imageMatrix`: espejo y cuartos de vuelta), no en los píxeles.
  - Los CMYK y los JPG que un lector de PDF podría no entender (sin pérdida, aritméticos) se tratan como las demás imágenes.
- **Las demás** (PNG, WebP, GIF, BMP, SVG):
  - Las dibuja la ventana en un `OffscreenCanvas`, ya orientadas.
  - Lado mayor: 6000 px como mucho; una SVG, a 2400 px.
  - Se guardan sin pérdida (`/FlateDecode` RGB) y, si hay transparencia, con una `/SMask`.
- Una misma imagen usada en varias páginas se escribe una vez.

`PdfWriter` es un escritor mínimo de PDF (objetos, páginas, tabla `xref`). Lo comparten también los
sellos ([`stamp-pdf.ts`](../../app/ui/src/tools/viewer/stamps/stamp-pdf.ts)).

## El documento nuevo (sin archivo)

```
ventana: imagesPdf → send(pdf) → viewer.create(nombre, url)
Python:  lo abre para leer páginas y tamaños, guarda los bytes (_OpenDocument.data)
ventana: pestaña del visor (shell._showDocument, con las páginas de imagen) → document_url
Python:  host.share_bytes(data) en vez de host.file_url(path)
```

- **Ruta:** es la sugerida para «Guardar como»: `~/Documents/<nombre>.pdf`, o `Imágenes (2).pdf`
  si ya hay otro abierto con esa ruta. La pestaña no la usa como ruta: así no se confunde con un
  archivo del disco con el mismo nombre.
- **`untitled: true`** en `DocumentState`:
  - está «sin guardar» desde el principio (la pestaña lleva ●);
  - aparece en el aviso al cerrar;
  - no entra en recientes.
- **Guardar:**
  - `viewer.save` responde `untitled`, y `DocumentActions.save` usa «Guardar como» directamente.
  - Tras guardar, `mark_saved` suelta los bytes y pasa a ser un documento normal.
- `file_size` (propiedades) da el tamaño de los bytes.

## Insertar y ajustar páginas

El motor de EmbedPDF (`lib/pdf-engine/native.ts`) tiene `stashPdf(data)`. Abre aparte el PDF de las
imágenes y copia sus páginas a un documento guardado, igual que las páginas borradas que se pueden
devolver (`stashPage`). Con eso, en
[`pages.ts`](../../app/ui/src/tools/viewer/document/pages.ts):

- `insertPdf(after, data)` pone las páginas detrás de `after` (`restorePages`), con claves nuevas,
  y se deshace quitándolas.
- `replaceWithPdf(index, data)` guarda la página actual y pone la nueva en su sitio; deshacer
  devuelve la anterior. Las anotaciones de la página rehecha se pierden (vuelven al deshacer).

`DocumentActions.imagePages` recuerda, por `uid` de página, la imagen, el giro y las opciones de cada
página hecha con una imagen **en esta sesión**. Se llena al crear el documento (`Viewer.svelte`
recibe `images` de la shell), al insertar y al ajustar. «Ajustar imagen…» solo está activo en esas
páginas. Al cerrar el visor se sueltan las imágenes. No se guarda nada en el PDF: al volver a
abrirlo, son páginas normales.

## Exportar páginas como imágenes

[`ExportImagesDialog.svelte`](../../app/ui/src/tools/viewer/document/ExportImagesDialog.svelte):

1. Se escriben antes las anotaciones pendientes (`view.commit`).
2. `viewer.pick_images_folder(doc_id)` pide la carpeta y devuelve `{folder, stem}`. Python apunta
   la carpeta.
3. Por cada página, el motor la dibuja tal como se ve y con sus anotaciones
   (`reading.pageImage`, a `ppp / 72` píxeles por punto). La ventana la codifica a PNG o JPG
   (`OffscreenCanvas.convertToBlob`, calidad 0,9) y la sube.
4. `viewer.save_page_image(folder, nombre, url)` la escribe con `host.write_file`. Solo acepta una
   carpeta elegida antes, un nombre sin rutas y la extensión `.png` o `.jpg`. En el navegador, la
   ventana la escribe en la carpeta elegida o la descarga.

Es distinto de «Extraer todas las imágenes del documento» (`viewer.export_images`), que saca las
imágenes incrustadas originales.

## Pruebas

| Qué | Dónde |
|---|---|
| Abrir imágenes, `images:open`, `image_url`, extensiones iguales en Python y en la ventana | `tests/test_images_to_pdf.py` |
| El PDF de las imágenes con el código real de `images.ts` (tarea `images` de `tests/engine_task.mjs`): JPG tal cual, orientación EXIF, giro, tamaños, márgenes | `tests/test_images_to_pdf.py` (`tests/fixtures/foto_exif6.jpg`, `gris.jpg`) |
| Insertar y rehacer páginas con el motor real (`insert-pdf`, `replace-pdf`) | `tests/test_images_to_pdf.py` |
| Documento sin archivo: guardar, guardar como, recientes, nombre repetido | `tests/test_images_to_pdf.py` |
| Exportar: solo en la carpeta elegida, nombres y extensiones | `tests/test_images_to_pdf.py` |

Los PNG, WebP y SVG necesitan un navegador para dibujarse, así que esa parte, el diálogo y la vista
previa se probaron con la versión de navegador en Edge (Playwright), no en la batería de pruebas.
Los diálogos nativos del escritorio (elegir imágenes y carpeta, arrastrar desde el Explorador) hay
que probarlos a mano.

## Límites conocidos

- «Ajustar imagen…» solo vale mientras el documento sigue abierto.
- Una página con varias imágenes no se puede crear: cada imagen es una página. Para poner una imagen
  encima de una página que ya existe, están los sellos de imagen (panel Sellos).
- Las imágenes que no son JPG se guardan sin pérdida: una foto grande en PNG da un PDF grande.
