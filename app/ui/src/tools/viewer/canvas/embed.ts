// EmbedPDF para el visor (pasos 2 a 4 de docs/web/embedpdf.md): el registro de toda la app
// con el motor PDFium, el gestor de documentos, la vista con scroll, el zoom, el mosaico, la
// doble página, la selección de texto, la búsqueda, las anotaciones (con su historial para
// deshacer y la exportación de la copia que se pasa a Python), las marcas de censura, los
// sellos y las firmas (sus bibliotecas: stamps/).
//
// EmbedPDF solo sabe desplazarse por todo el documento. Para los modos «Una página» y
// «Doble página» (paginados, como en Qt) el complemento de scroll lleva una estrategia
// más: `paged`, que muestra solo una fila (una página o un par) y deja cambiar de fila
// con `showRow`.
import { mount } from 'svelte';
import { createPluginRegistration, type PluginRegistry } from '@embedpdf/core';
import { AnnotationPluginPackage, LockModeType } from '@embedpdf/plugin-annotation';
import { DocumentManagerPluginPackage } from '@embedpdf/plugin-document-manager';
import { ExportPluginPackage } from '@embedpdf/plugin-export';
import { HistoryPluginPackage } from '@embedpdf/plugin-history';
import { InteractionManagerPluginPackage, type InteractionManagerPlugin } from '@embedpdf/plugin-interaction-manager';
import { RedactionPluginPackage } from '@embedpdf/plugin-redaction';
import { RenderPluginPackage } from '@embedpdf/plugin-render';
import { RotatePluginPackage } from '@embedpdf/plugin-rotate';
import { SCROLL_PLUGIN_ID, ScrollPlugin, ScrollPluginPackage, ScrollStrategy, type ScrollPluginConfig } from '@embedpdf/plugin-scroll';
import { SearchPluginPackage } from '@embedpdf/plugin-search';
import { SelectionPluginPackage } from '@embedpdf/plugin-selection';
import { SignatureMode, SignaturePluginPackage } from '@embedpdf/plugin-signature';
import { SpreadPluginPackage } from '@embedpdf/plugin-spread';
import { StampPluginPackage } from '@embedpdf/plugin-stamp';
import { TilingPluginPackage } from '@embedpdf/plugin-tiling';
import { ViewportPluginPackage } from '@embedpdf/plugin-viewport';
import { ZoomPluginPackage } from '@embedpdf/plugin-zoom';
import wasmUrl from '@embedpdf/pdfium/pdfium.wasm?url';
import { STANDARD_LIBRARY } from '../stamps/standard.ts';
import { t } from '$texts';
import { DEFAULT_STYLE as STYLE, PRESET_COLORS } from '../annotations/palette.ts';
import EmbedRoot from './EmbedRoot.svelte';

export const UNIT = 2; // píxeles por punto PDF al 100 % (como el lienzo Qt: una carta mide 1224 px)
export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 4;
export const PAGED = 'paged';
const PAGE_GAP = 12; // puntos entre páginas (24 px al 100 %)
export const VIEWPORT_GAP = 40; // px alrededor del contenido; también el margen al ajustar
const IMAGE = { type: 'image/webp', quality: 0.92 } as const;
// Modos del gestor de interacción: con el de texto (el predeterminado de EmbedPDF) se
// selecciona texto; con el de las demás herramientas, no (dibujan otros módulos).
export const TEXT_MODE = 'pointerMode';
export const OTHER_MODE = 'viewer-tools';

// Herramientas de anotación de EmbedPDF con nuestros valores iniciales (se mezclan con los
// suyos). Cada visor les aplica después su propio estilo al activarlas (annotations.ts).
const markup = (color: string) => ({ defaults: { strokeColor: color, color } });
const shape = { defaults: { strokeColor: STYLE.shapeColor, strokeWidth: STYLE.shapeWidth } };
const TEXT = t.viewer.canvas.defaultText;
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
    defaults: { contents: TEXT, fontColor: STYLE.penColor, fontSize: STYLE.fontSize },
    clickBehavior: { enabled: true, defaultSize: { width: 120, height: 22 }, defaultContent: TEXT },
  },
  {
    id: 'freeTextCallout',
    defaults: {
      contents: TEXT, fontColor: STYLE.penColor, fontSize: STYLE.fontSize, strokeColor: STYLE.penColor, strokeWidth: 1,
    },
  },
  { id: 'textComment', defaults: { strokeColor: STYLE.noteColor, color: STYLE.noteColor } },
  { id: 'link', categories: ['link'] }, // bloqueados (ver `locked`)
];

let registryPromise: Promise<PluginRegistry> | null = null;

/**
 * El registro de EmbedPDF, uno para toda la app: cada visor abre en él su documento con
 * un id propio. Tiene que ser uno solo porque los componentes de Svelte de EmbedPDF leen
 * el registro de una variable global (con dos `<EmbedPDF>`, el último pisa al primero).
 * Los componentes (PdfPages.svelte) se montan después de que esté listo.
 */
export function registry(): Promise<PluginRegistry> {
  registryPromise ??= (async () => {
    // El motor PDFium corre en un worker. El WASM va dentro de la app: sin internet. Su
    // URL va absoluta: el worker nace de un blob: y no resolvería una relativa (en
    // desarrollo Vite la da como /node_modules/…, y el motor se quedaba esperando).
    const { createPdfiumEngine } = await import('@embedpdf/engines/pdfium-worker-engine');
    const engine = await createPdfiumEngine(new URL(wasmUrl, location.href).href, { fontFallback: null });
    const embed = await new Promise<PluginRegistry>((resolve) => {
      mount(EmbedRoot, { target: document.createElement('div'), props: { engine, plugins: plugins(), onReady: resolve } });
    });
    // Sin `wantsRawTouch`: en pantallas táctiles el dedo sigue desplazando las páginas.
    const interaction = embed.getPlugin<InteractionManagerPlugin>('interaction-manager')!.provides();
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
    // son del documento.
    createPluginRegistration(AnnotationPluginPackage, {
      tools: ANNOTATION_TOOLS,
      colorPresets: PRESET_COLORS.map(([color]) => color),
      locked: { type: LockModeType.Include, categories: ['link'] },
    } as Parameters<typeof AnnotationPluginPackage.create>[1]),
    // Censura: las marcas pendientes son anotaciones (se revisan, se mueven, se borran y se
    // deshacen como las demás); se aplican en Python con el motor (redaction.ts).
    createPluginRegistration(RedactionPluginPackage, { useAnnotationMode: true, drawBlackBoxes: true }),
    // Sellos: los estándar van dentro de la app (sin la descarga de su CDN que trae por
    // defecto); los de texto y los propios los carga stamps/library.svelte.ts.
    createPluginRegistration(StampPluginPackage, { libraries: [STANDARD_LIBRARY], manifests: [], defaultLibrary: false }),
    createPluginRegistration(SignaturePluginPackage, { mode: SignatureMode.SignatureAndInitials }),
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

/**
 * Estrategia de colocación del complemento de scroll. Sus métodos son protegidos o internos en
 * EmbedPDF 2.15.1: aquí solo se declaran los que sustituye la estrategia paginada.
 */
interface Strategy {
  paged?: boolean;
  row?: number;
  createVirtualItems(spreads: any[]): any[];
  getTotalContentSize(items: any[]): { width: number; height: number };
  getVisibleRange(viewport: any, items: any[], scale: number): { start: number; end: number };
  handleScroll(viewport: any, items: any[], scale: number): Record<string, unknown>;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

/**
 * Lo interno de ScrollPlugin que usa el visor: crear la estrategia de cada documento, la de
 * cada documento abierto y volver a colocar sus páginas. Es privado en EmbedPDF 2.15.1:
 * revisarlo al actualizarlo.
 */
interface ScrollInternals {
  strategies: Map<string, Strategy>;
  createStrategy(type: string): Strategy;
  refreshDocumentLayout(documentId: string): void;
}

/** Lo público de ScrollPlugin (`keyof` deja fuera lo privado) más lo interno que se usa. */
export type ViewerScroll = Pick<ScrollPlugin, keyof ScrollPlugin> & ScrollInternals & { showRow(documentId: string, row: number): void };

const ScrollBase = ScrollPlugin as unknown as new (id: string, registry: PluginRegistry, config?: ScrollPluginConfig) =>
  Pick<ScrollPlugin, keyof ScrollPlugin> & ScrollInternals;

/** Scroll de EmbedPDF con la estrategia paginada además de la vertical. */
export class ViewerScrollPlugin extends ScrollBase {
  createStrategy(type: string): Strategy {
    const vertical = super.createStrategy(ScrollStrategy.Vertical);
    return type === PAGED ? pagedStrategy(vertical) : vertical;
  }

  /** Muestra la fila `row` en el modo paginado (no hace nada en el continuo). */
  showRow(documentId: string, row: number): void {
    const strategy = this.strategies.get(documentId);
    if (!strategy?.paged || strategy.row === row) return;
    strategy.row = row;
    this.refreshDocumentLayout(documentId);
  }
}

const ViewerScrollPackage = {
  ...ScrollPluginPackage,
  create: (registry: PluginRegistry, config?: ScrollPluginConfig) =>
    new ViewerScrollPlugin(SCROLL_PLUGIN_ID, registry, config) as unknown as ScrollPlugin,
};

/**
 * La estrategia vertical con todas las filas en el origen y solo la fila `row` a la vista:
 * el contenido mide lo que esa fila y el scroll se mueve dentro de ella.
 */
function pagedStrategy(vertical: Strategy): Strategy {
  const strategy: Strategy = Object.create(vertical);
  const current = <T>(items: T[]) => items[Math.min(strategy.row ?? 0, items.length - 1)] as T | undefined;
  return Object.assign(strategy, {
    paged: true,
    row: 0,
    createVirtualItems(this: Strategy, spreads: unknown[]) {
      return vertical.createVirtualItems.call(this, spreads).map((item) => ({ ...item, y: 0, offset: 0 }));
    },
    getTotalContentSize(items: { width: number; height: number }[]) {
      const item = current(items);
      return item ? { width: item.width, height: item.height } : { width: 0, height: 0 };
    },
    getVisibleRange(_viewport: unknown, items: unknown[]) {
      const row = Math.min(strategy.row ?? 0, items.length - 1);
      return { start: row, end: row };
    },
    handleScroll(this: Strategy, viewport: unknown, items: unknown[], scale: number) {
      return { ...vertical.handleScroll.call(this, viewport, items, scale), startSpacing: 0, endSpacing: 0 };
    },
  });
}
