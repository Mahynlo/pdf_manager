// EmbedPDF para el visor (pasos 2 a 4 de docs/web/embedpdf.md): el registro de toda la app
// con el motor PDFium, el gestor de documentos, la vista con scroll, el zoom, el mosaico, la
// doble página, la selección de texto, la búsqueda, las anotaciones (con su historial para
// deshacer y la exportación de la copia que se pasa a Python) y las marcas de censura.
//
// EmbedPDF solo sabe desplazarse por todo el documento. Para los modos «Una página» y
// «Doble página» (paginados, como en Qt) el complemento de scroll lleva una estrategia
// más: `paged`, que muestra solo una fila (una página o un par) y deja cambiar de fila
// con `showRow`.
import { mount } from 'svelte';
import { createPluginRegistration } from '@embedpdf/core';
import { AnnotationPluginPackage, LockModeType } from '@embedpdf/plugin-annotation';
import { DocumentManagerPluginPackage } from '@embedpdf/plugin-document-manager';
import { ExportPluginPackage } from '@embedpdf/plugin-export';
import { HistoryPluginPackage } from '@embedpdf/plugin-history';
import { InteractionManagerPluginPackage } from '@embedpdf/plugin-interaction-manager';
import { RedactionPluginPackage } from '@embedpdf/plugin-redaction';
import { RenderPluginPackage } from '@embedpdf/plugin-render';
import { RotatePluginPackage } from '@embedpdf/plugin-rotate';
import { SCROLL_PLUGIN_ID, ScrollPlugin, ScrollPluginPackage, ScrollStrategy } from '@embedpdf/plugin-scroll';
import { SearchPluginPackage } from '@embedpdf/plugin-search';
import { SelectionPluginPackage } from '@embedpdf/plugin-selection';
import { SpreadPluginPackage } from '@embedpdf/plugin-spread';
import { TilingPluginPackage } from '@embedpdf/plugin-tiling';
import { ViewportPluginPackage } from '@embedpdf/plugin-viewport';
import { ZoomPluginPackage } from '@embedpdf/plugin-zoom';
import wasmUrl from '@embedpdf/pdfium/pdfium.wasm?url';
import EmbedRoot from './EmbedRoot.svelte';
import { DEFAULT_STYLE as STYLE, PRESET_COLORS } from './palette.js';

export const UNIT = 2; // píxeles por punto PDF al 100 % (como el lienzo Qt: una carta mide 1224 px)
export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 4;
export const PAGED = 'paged';
const PAGE_GAP = 12; // puntos entre páginas (24 px al 100 %)
export const VIEWPORT_GAP = 40; // px alrededor del contenido; también el margen al ajustar
const IMAGE = { type: 'image/webp', quality: 0.92 };
// Modos del gestor de interacción: con el de texto (el predeterminado de EmbedPDF) se
// selecciona texto; con el de las demás herramientas, no (dibujan otros módulos).
export const TEXT_MODE = 'pointerMode';
export const OTHER_MODE = 'viewer-tools';

// Herramientas de anotación de EmbedPDF con nuestros valores iniciales (se mezclan con los
// suyos). Cada visor les aplica después su propio estilo al activarlas (annotations.js).
const markup = (color) => ({ defaults: { strokeColor: color, color } });
const shape = { defaults: { strokeColor: STYLE.shapeColor, strokeWidth: STYLE.shapeWidth } };
const ANNOTATION_TOOLS = [
  { id: 'highlight', ...markup(STYLE.highlightColor) },
  { id: 'underline', ...markup(STYLE.underlineColor) },
  { id: 'strikeout', ...markup(STYLE.strikeoutColor) },
  { id: 'squiggly', ...markup(STYLE.squigglyColor) },
  { id: 'square', ...shape },
  { id: 'circle', ...shape },
  { id: 'polyline', ...shape },
  { id: 'polygon', ...shape },
  { id: 'line', defaults: { strokeColor: STYLE.penColor, strokeWidth: STYLE.shapeWidth } },
  { id: 'lineArrow', defaults: { strokeColor: STYLE.penColor, strokeWidth: STYLE.shapeWidth } },
  { id: 'ink', defaults: { strokeColor: STYLE.penColor, strokeWidth: STYLE.penWidth } },
  { id: 'inkHighlighter', defaults: { strokeColor: STYLE.highlightColor, strokeWidth: STYLE.markerWidth } },
  {
    id: 'freeText',
    defaults: { contents: 'Texto', fontColor: STYLE.penColor, fontSize: STYLE.fontSize },
    clickBehavior: { enabled: true, defaultSize: { width: 120, height: 22 }, defaultContent: 'Texto' },
  },
  {
    id: 'freeTextCallout',
    defaults: {
      contents: 'Texto', fontColor: STYLE.penColor, fontSize: STYLE.fontSize, strokeColor: STYLE.penColor, strokeWidth: 1,
    },
  },
  { id: 'textComment', defaults: { strokeColor: STYLE.noteColor, color: STYLE.noteColor } },
  { id: 'link', categories: ['link'] }, // bloqueados (ver `locked`)
];

let registryPromise = null;

/**
 * El registro de EmbedPDF, uno para toda la app: cada visor abre en él su documento con
 * un id propio. Tiene que ser uno solo porque los componentes de Svelte de EmbedPDF leen
 * el registro de una variable global (con dos `<EmbedPDF>`, el último pisa al primero).
 * Los componentes (PdfPages.svelte) se montan después de que esté listo.
 */
export function registry() {
  registryPromise ??= (async () => {
    // El motor PDFium corre en un worker. El WASM va dentro de la app: sin internet. Su
    // URL va absoluta: el worker nace de un blob: y no resolvería una relativa (en
    // desarrollo Vite la da como /node_modules/…, y el motor se quedaba esperando).
    const { createPdfiumEngine } = await import('@embedpdf/engines/pdfium-worker-engine');
    const engine = await createPdfiumEngine(new URL(wasmUrl, location.href).href, { fontFallback: null });
    const embed = await new Promise((resolve) => {
      mount(EmbedRoot, { target: document.createElement('div'), props: { engine, plugins: plugins(), onReady: resolve } });
    });
    // Sin `wantsRawTouch`: en pantallas táctiles el dedo sigue desplazando las páginas.
    const interaction = embed.getPlugin('interaction-manager').provides();
    for (const id of [TEXT_MODE, OTHER_MODE]) interaction.registerMode({ id, scope: 'page', exclusive: false, wantsRawTouch: false });
    return embed;
  })();
  return registryPromise;
}

function plugins() {
  return [
    createPluginRegistration(DocumentManagerPluginPackage),
    createPluginRegistration(ViewportPluginPackage, { viewportGap: VIEWPORT_GAP }),
    createPluginRegistration(ViewerScrollPackage, { defaultPageGap: PAGE_GAP, defaultBufferSize: 2 }),
    createPluginRegistration(SpreadPluginPackage),
    // Gira con CSS cada página según su /Rotate (componente Rotate de PdfPages.svelte).
    createPluginRegistration(RotatePluginPackage),
    createPluginRegistration(InteractionManagerPluginPackage),
    // Selección arrastrando, palabra con doble clic y línea con triple; sin la de rectángulo.
    createPluginRegistration(SelectionPluginPackage, { marquee: { enabled: false } }),
    createPluginRegistration(SearchPluginPackage),
    createPluginRegistration(HistoryPluginPackage),
    // Las anotaciones las dibuja y edita su capa (PdfPage.svelte); los enlaces quedan bloqueados:
    // son del documento (Python conserva los suyos al guardar, ver pdf_core/annot_transfer.py).
    createPluginRegistration(AnnotationPluginPackage, {
      tools: ANNOTATION_TOOLS,
      colorPresets: PRESET_COLORS.map(([color]) => color),
      locked: { type: LockModeType.Include, categories: ['link'] },
    }),
    // Censura: las marcas pendientes son anotaciones (se revisan, se mueven, se borran y se
    // deshacen como las demás); la censura la aplica Python (redaction.js).
    createPluginRegistration(RedactionPluginPackage, { useAnnotationMode: true, drawBlackBoxes: true }),
    createPluginRegistration(ExportPluginPackage, { defaultFileName: 'documento.pdf' }),
    // Sin las anotaciones: las dibuja su capa encima (si no, saldrían dos veces).
    createPluginRegistration(RenderPluginPackage, {
      withAnnotations: false, withForms: true, defaultImageType: IMAGE.type, defaultImageQuality: IMAGE.quality,
    }),
    createPluginRegistration(TilingPluginPackage, { tileSize: 768, overlapPx: 2.5, extraRings: 0, defaultImageType: IMAGE.type }),
    createPluginRegistration(ZoomPluginPackage, {
      defaultZoomLevel: UNIT, minZoom: ZOOM_MIN * UNIT, maxZoom: ZOOM_MAX * UNIT,
    }),
  ];
}

/** Scroll de EmbedPDF con la estrategia paginada además de la vertical. */
class ViewerScrollPlugin extends ScrollPlugin {
  createStrategy(type) {
    const vertical = super.createStrategy(ScrollStrategy.Vertical);
    return type === PAGED ? pagedStrategy(vertical) : vertical;
  }

  /** Muestra la fila `row` en el modo paginado (no hace nada en el continuo). */
  showRow(documentId, row) {
    const strategy = this.strategies.get(documentId);
    if (!strategy?.paged || strategy.row === row) return;
    strategy.row = row;
    this.refreshDocumentLayout(documentId);
  }
}

const ViewerScrollPackage = {
  ...ScrollPluginPackage,
  create: (registry, config) => new ViewerScrollPlugin(SCROLL_PLUGIN_ID, registry, config),
};

/**
 * La estrategia vertical con todas las filas en el origen y solo la fila `row` a la vista:
 * el contenido mide lo que esa fila y el scroll se mueve dentro de ella.
 */
function pagedStrategy(vertical) {
  const strategy = Object.create(vertical);
  const current = (items) => items[Math.min(strategy.row, items.length - 1)];
  return Object.assign(strategy, {
    paged: true,
    row: 0,
    createVirtualItems(spreads) {
      return vertical.createVirtualItems.call(this, spreads).map((item) => ({ ...item, y: 0, offset: 0 }));
    },
    getTotalContentSize(items) {
      const item = current(items);
      return item ? { width: item.width, height: item.height } : { width: 0, height: 0 };
    },
    getVisibleRange(_viewport, items) {
      const row = Math.min(strategy.row, items.length - 1);
      return { start: row, end: row };
    },
    handleScroll(viewport, items, scale) {
      return { ...vertical.handleScroll.call(this, viewport, items, scale), startSpacing: 0, endSpacing: 0 };
    },
  });
}
