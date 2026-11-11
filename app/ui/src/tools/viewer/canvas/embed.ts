// EmbedPDF para el visor (docs/web/embedpdf.md): el registro de toda la app con el motor PDFium
// (lib/pdf-engine), el gestor de documentos, la vista con scroll, el zoom, el mosaico, la doble
// página, la selección de texto, la búsqueda, las anotaciones (con su historial para deshacer),
// las marcas de censura, los sellos y las firmas (sus bibliotecas: stamps/). También lo que hace
// falta para cambiar las páginas de un documento abierto (`showPageList`), que EmbedPDF 2.15.1 no
// contempla. Las copias del documento (guardar, imprimir, pasarlo a Python) las saca el motor de
// la app (`copies`), no el complemento de exportación.
//
// EmbedPDF solo sabe desplazarse por todo el documento. Para los modos «Una página» y
// «Doble página» (paginados, como en Qt) el complemento de scroll lleva una estrategia
// más: `paged`, que muestra solo una fila (una página o un par) y deja cambiar de fila
// con `showRow`.
import { mount } from 'svelte';
import { createPluginRegistration, refreshPages, type PluginRegistry } from '@embedpdf/core';
import type { PdfPageObject } from '@embedpdf/models';
import { AnnotationPluginPackage, LockModeType } from '@embedpdf/plugin-annotation';
import { DocumentManagerPluginPackage } from '@embedpdf/plugin-document-manager';
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
import { createAppEngine, type AppEngine, type DocumentCopies, type PageStructure } from '$lib/pdf-engine/index.ts';
import { STANDARD_LIBRARY } from '../stamps/standard.ts';
import { t } from '$texts';
import { DEFAULT_STYLE as STYLE, PRESET_COLORS } from '../annotations/palette.ts';
import EmbedRoot from './EmbedRoot.svelte';

export const UNIT = 2; // píxeles por punto PDF al 100 % (como el lienzo Qt: una carta mide 1224 px)
export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 4;
export const PAGED = 'paged';
const PAGE_GAP = 12; // puntos entre páginas (24 px al 100 %)
// px alrededor del contenido; también el margen al ajustar. En pantallas estrechas, la página manda.
export const VIEWPORT_GAP = matchMedia('(max-width: 839.98px)').matches ? 8 : 40;
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
let appEngine: AppEngine | null = null; // el motor (lib/pdf-engine), creado con el registro

/**
 * El registro de EmbedPDF, uno para toda la app: cada visor abre en él su documento con
 * un id propio. Tiene que ser uno solo porque los componentes de Svelte de EmbedPDF leen
 * el registro de una variable global (con dos `<EmbedPDF>`, el último pisa al primero).
 * Los componentes (PdfPages.svelte) se montan después de que esté listo.
 */
export function registry(): Promise<PluginRegistry> {
  registryPromise ??= (async () => {
    // El motor PDFium corre en un worker (lib/pdf-engine). El WASM va dentro de la app: sin
    // internet. Su URL va absoluta: en desarrollo Vite la da como /node_modules/….
    appEngine = createAppEngine(new URL(wasmUrl, location.href).href);
    const { engine } = appEngine;
    const embed = await new Promise<PluginRegistry>((resolve) => {
      mount(EmbedRoot, { target: document.createElement('div'), props: { engine, plugins: plugins(), onReady: resolve } });
    });
    acceptPageLists(embed);
    // Sin `wantsRawTouch`, el dedo desplaza las páginas. En una pantalla táctil, salvo con las
    // herramientas de texto: ahí arrastrar selecciona (para desplazar está la mano).
    const interaction = embed.getPlugin<InteractionManagerPlugin>('interaction-manager')!.provides();
    const touch = matchMedia('(pointer: coarse)').matches;
    for (const id of [TEXT_MODE, OTHER_MODE]) {
      interaction.registerMode({ id, scope: 'page', exclusive: false, wantsRawTouch: touch && id === TEXT_MODE });
    }
    return embed;
  })();
  return registryPromise;
}

/** Las operaciones del motor que cambian las páginas de un documento abierto (lib/pdf-engine). */
export async function structure(): Promise<PageStructure> {
  await registry();
  return appEngine!.structure;
}

/** Las copias del documento abierto que salen del visor (lib/pdf-engine). */
export async function copies(): Promise<DocumentCopies> {
  await registry();
  return appEngine!.copies;
}

// ── Cambiar las páginas de un documento abierto ──────────────────────────────
// EmbedPDF 2.15.1 no lo contempla: solo carga las páginas al abrir el documento. Lo que sigue
// usa partes internas de su núcleo y de sus complementos: revisarlo al actualizar EmbedPDF.

const SET_PAGES = 'SET_PAGES'; // la declara el núcleo, pero su reductor no la atiende
const SET_PAGE_GROUPING = 'SPREAD/SET_PAGE_GROUPING';

type Action = { type: string; payload?: unknown };

/** Lo que se usa del estado del núcleo de EmbedPDF. */
interface CoreState {
  documents: Record<string, { document: { pages: PdfPageObject[]; pageCount: number } | null } | undefined>;
}

/** Lo que se usa del store de EmbedPDF (su reductor del núcleo es una propiedad pública). */
interface CoreStore {
  coreReducer: (state: CoreState, action: Action) => CoreState;
  getState(): { core: CoreState };
  dispatchToCore(action: Action): unknown;
}

/** Lo interno de SpreadPlugin: agrupa las páginas (una o dos por fila) solo al abrir. */
interface SpreadInternals {
  calculatePageGrouping(documentId: string, pageCount: number): number[][];
  dispatch(action: Action): void;
}

/** Lo interno de AnnotationPlugin: carga las anotaciones de todo el documento. */
interface AnnotationInternals {
  getAllAnnotations(documentId: string, document: unknown): void;
  appearanceCache: Map<string, unknown>; // imágenes de las anotaciones, por documento y número de página
}

/** Hace que el núcleo atienda SET_PAGES: el documento pasa a tener esas páginas. */
function acceptPageLists(embed: PluginRegistry): void {
  const store = embed.getStore() as unknown as CoreStore;
  const reducer = store.coreReducer;
  store.coreReducer = (state, action) => {
    if (action.type !== SET_PAGES) return reducer(state, action);
    const { documentId, pages } = action.payload as { documentId: string; pages: PdfPageObject[] };
    const docState = state.documents[documentId];
    if (!docState?.document) return state;
    // Un documento nuevo en el estado: así los complementos ven el cambio.
    const document = { ...docState.document, pages, pageCount: pages.length };
    return { ...state, documents: { ...state.documents, [documentId]: { ...docState, document } } };
  };
}

/**
 * Muestra `pages`, las páginas que tiene ahora en el motor el documento abierto `documentId`:
 * todas se vuelven a dibujar (su número ya no dice qué página es), se agrupan y colocan de
 * nuevo, y se vuelven a leer sus anotaciones y sus imágenes.
 */
export function showPageList(embed: PluginRegistry, documentId: string, pages: PdfPageObject[]): void {
  const store = embed.getStore() as unknown as CoreStore;
  store.dispatchToCore({ type: SET_PAGES, payload: { documentId, pages } });
  store.dispatchToCore(refreshPages(documentId, pages.map((page) => page.index)));
  const spread = embed.getPlugin('spread') as unknown as SpreadInternals;
  spread.dispatch({ type: SET_PAGE_GROUPING, payload: { documentId, grouping: spread.calculatePageGrouping(documentId, pages.length) } });
  (embed.getPlugin('scroll') as unknown as ViewerScroll).refreshDocumentLayout(documentId);
  const annotations = embed.getPlugin('annotation') as unknown as AnnotationInternals;
  annotations.appearanceCache.delete(documentId);
  annotations.getAllAnnotations(documentId, store.getState().core.documents[documentId]!.document);
}

/** Lo que se usa del estado de plugin-annotation. */
interface AnnotationState {
  documents: Record<string, { pages: Record<number, string[]>; byUid: Record<string, unknown> } | undefined>;
}

/**
 * SET_ANNOTATIONS sustituye todas las anotaciones del documento. La de plugin-annotation 2.15.1
 * borra además las que antes estaban en el mismo número de página, aunque acabe de ponerlas en
 * otra: al mover páginas, las anotaciones se quedaban sin datos y su capa fallaba.
 */
function setAllAnnotations(state: AnnotationState, action: Action): AnnotationState {
  const { documentId, annotations } = action.payload as { documentId: string; annotations: Record<number, { id: string }[]> };
  const docState = state.documents[documentId];
  if (!docState) return state;
  const pages: Record<number, string[]> = {};
  const byUid: Record<string, unknown> = {};
  for (const [page, list] of Object.entries(annotations)) {
    pages[Number(page)] = list.map((object) => {
      byUid[object.id] = { commitState: 'synced', object };
      return object.id;
    });
  }
  return { ...state, documents: { ...state.documents, [documentId]: { ...docState, pages, byUid } } };
}

const ViewerAnnotationPackage = {
  ...AnnotationPluginPackage,
  reducer: ((state, action) =>
    action.type === 'ANNOTATION/SET_ANNOTATIONS'
      ? setAllAnnotations(state as unknown as AnnotationState, action)
      : AnnotationPluginPackage.reducer(state, action)) as typeof AnnotationPluginPackage.reducer,
};

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
    createPluginRegistration(ViewerAnnotationPackage, {
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
    // Sin las anotaciones: las dibuja su capa encima (si no, saldrían dos veces).
    createPluginRegistration(RenderPluginPackage, {
      withAnnotations: false, withForms: true, defaultImageType: IMAGE.type, defaultImageQuality: IMAGE.quality,
    }),
    createPluginRegistration(ViewerTilingPackage, { tileSize: 768, overlapPx: 2.5, extraRings: 0, defaultImageType: IMAGE.type }),
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

/** Lo que se usa del estado de plugin-tiling. */
interface TilingState {
  documents: Record<string, { visibleTiles: Record<number, { id: string; isFallback: boolean }[]> }>;
}

/**
 * Quita los mosaicos repetidos: entre uno de respaldo y uno nuevo, se queda el nuevo. Al cambiar de
 * zoom, plugin-tiling (2.15.1) conserva los mosaicos anteriores de respaldo; si se vuelve a ese zoom
 * antes de que acaben los del otro, crea unos con el mismo id, y la lista de Svelte, cuya clave es
 * ese id, falla y deja el visor sin responder. Hay que revisarlo al actualizar EmbedPDF.
 */
function withoutRepeatedTiles<S extends TilingState>(state: S): S {
  let documents = state.documents;
  for (const [id, doc] of Object.entries(state.documents)) {
    for (const [page, tiles] of Object.entries(doc.visibleTiles)) {
      const unique = new Map<string, (typeof tiles)[number]>();
      for (const tile of tiles) {
        if (!tile.isFallback || !unique.has(tile.id)) unique.set(tile.id, tile);
      }
      if (unique.size === tiles.length) continue;
      const current = documents[id];
      documents = { ...documents, [id]: { ...current, visibleTiles: { ...current.visibleTiles, [page]: [...unique.values()] } } };
    }
  }
  return documents === state.documents ? state : { ...state, documents };
}

const ViewerTilingPackage = {
  ...TilingPluginPackage,
  reducer: ((state, action) => {
    const next = TilingPluginPackage.reducer(state, action);
    return next === state ? state : withoutRepeatedTiles(next);
  }) as typeof TilingPluginPackage.reducer,
};

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
