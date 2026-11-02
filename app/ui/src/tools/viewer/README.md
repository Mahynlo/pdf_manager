# Visor de PDF (`tools/viewer`)

`Viewer.svelte` es la pestaña de un PDF (la carga `shell/tools.js`) y compone todo lo demás. Cada
carpeta agrupa una parte del visor:

| Carpeta | Qué contiene |
|---|---|
| `canvas/` | El lienzo con EmbedPDF: el registro y sus complementos (`embed.js`, `EmbedRoot.svelte`), la clase `PageCanvas` con zoom, modos de vista y herramientas (`canvas.js`, `layout.js`), las páginas (`PdfPages.svelte`, `PdfPage.svelte`) y la selección de texto (`selection.js`) |
| `annotations/` | Anotaciones: el modelo sobre EmbedPDF (`annotations.js`), la barra de propiedades y el teclado (`editing.js`), colores y estilos (`palette.js`), y los sellos y leyendas (`stamps.js`, `LegendsDialog.svelte`) |
| `redact/` | Censura: las marcas (`redaction.js`), el panel (`RedactPanel.svelte`) y los perfiles (`ProfilesDialog.svelte`) |
| `ocr/` | OCR: el panel y sus diálogos de lote y resultado |
| `document/` | Acciones sobre el archivo: guardar, páginas y exportar (`operations.js`), imprimir (`PrintDialog.svelte`, `print.js`) y propiedades |
| `toolbars/` | La barra superior (`Toolbar.svelte`) y la de herramientas del lienzo (`ToolsBar.svelte`) |
| `panels/` | Los demás paneles: miniaturas (`Thumbnails.svelte`), índice, búsqueda y asistente IA |

Reglas:
- Lo que solo usa el visor va aquí; lo que comparten varias herramientas va en `$lib`.
- Una carpeta por función. Si un panel crece con su propio modelo o diálogos, pasa de `panels/` a
  su propia carpeta, como `ocr/` y `redact/`.
- Importaciones relativas entre carpetas (`../canvas/canvas.js`) y `$lib/...` para lo común.

Cómo funciona por dentro (EmbedPDF y Python): [docs/web/embedpdf.md](../../../../../docs/web/embedpdf.md).
