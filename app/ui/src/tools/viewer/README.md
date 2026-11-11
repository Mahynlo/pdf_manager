# Visor de PDF (`tools/viewer`)

`Viewer.svelte` es la pestaña de un PDF (la carga `shell/tools.ts`) y compone todo lo demás. Cada
carpeta agrupa una parte del visor:

| Carpeta | Qué contiene |
|---|---|
| `canvas/` | El lienzo con EmbedPDF: el registro y sus complementos (`embed.ts`, `EmbedRoot.svelte`), la clase `PageCanvas` con zoom, modos de vista y herramientas (`canvas.ts`, `layout.ts`), las páginas (`PdfPages.svelte`, `PdfPage.svelte`) y la selección de texto (`selection.ts`) |
| `annotations/` | Anotaciones: el modelo sobre EmbedPDF (`annotations.ts`), la barra de propiedades y el teclado (`editing.ts`), y colores y estilos (`palette.ts`) |
| `stamps/` | Sellos y firmas: las bibliotecas (`library.svelte.ts`, `standard.ts`), el PDF de cada sello (`stamp-pdf.ts`), las firmas (`signatures.svelte.ts`), el panel (`StampsPanel.svelte`) y los diálogos de firma y de leyendas |
| `redact/` | Censura: las marcas (`redaction.ts`), el panel (`RedactPanel.svelte`) y los perfiles (`ProfilesDialog.svelte`) |
| `ocr/` | OCR: el panel y sus diálogos de lote y resultado |
| `document/` | Acciones sobre el archivo: guardar, páginas y exportar (`operations.ts`), las operaciones de página con el motor de EmbedPDF y su deshacer (`pages.ts`), la copia del documento que sale del visor a Python, a un archivo o a la impresora (`copy.ts`; las dos sobre `$lib/pdf-engine`), imprimir con el diálogo de WebView2 (`print.ts`) y las propiedades (`properties.ts`, `PropertiesDialog.svelte`) |
| `toolbars/` | La barra superior (`Toolbar.svelte`) y la de herramientas del lienzo (`ToolsBar.svelte`) |
| `panels/` | Los demás paneles: miniaturas (`Thumbnails.svelte`), índice, búsqueda y asistente IA |

Reglas:
- Lo que solo usa el visor va aquí; lo que comparten varias herramientas va en `$lib`.
- Una carpeta por función. Si un panel crece con su propio modelo o diálogos, pasa de `panels/` a
  su propia carpeta, como `ocr/` y `redact/`.
- Importaciones relativas entre carpetas (`../canvas/canvas.ts`) y `$lib/...` para lo común.
- Los textos van en el catálogo (`t.viewer`, en `src/texts/es/viewer.ts`) y las respuestas de Python
  de una parte, en su `types.ts` (`ocr/types.ts`).

Cómo funciona por dentro (EmbedPDF y Python): [docs/web/embedpdf.md](../../../../../docs/web/embedpdf.md).
