// Lienzo del visor: las páginas con zoom, modos de vista y modo noche.
// Desde el paso 2 de docs/web/embedpdf.md las páginas,
// el scroll, el zoom y el mosaico son de EmbedPDF (embed.ts, PdfPages.svelte); esta
// clase da al resto del visor la misma API que antes. El registro de EmbedPDF es uno para
// toda la app: cada visor abre en él su documento y solo atiende los avisos de ese documento.
//
// - Las operaciones de página (girar, mover, insertar, duplicar, borrar) las hace el motor de
//   EmbedPDF en el documento abierto (document/pages.ts) y `showPages` las muestra sin volver a
//   abrirlo. Lo que cambia Python (censurar) se vuelve a abrir en EmbedPDF con la versión
//   que él tiene (`viewer.document_url`); mientras se carga, la vista sigue con la anterior.
//   document/copy.ts le pasa a Python la copia de EmbedPDF antes de lo que la necesita.
// - El texto reconocido por OCR lo escribe el motor en el documento abierto como texto invisible
//   (`writeOcrText`), que EmbedPDF selecciona y busca como el nativo: al abrir una versión, el
//   que guarda Python, y tras cada OCR, el nuevo.
// - Cada página tiene una capa del visor (`slots[i]`) donde otros módulos dibujan en
//   porcentaje de la página las marcas (`marks(i)`) de selección, búsqueda, OCR o censura.
//   Las capas existen siempre, aunque EmbedPDF solo monte las páginas a la vista; se
//   enganchan a la página al montarse.
// - `el` es el contenedor con scroll (la vista de EmbedPDF): ahí escuchan el ratón los
//   demás módulos. La selección de texto es de EmbedPDF (selection.ts): está activa con las
//   herramientas de texto (modo TEXT_MODE del gestor de interacción). Las de dibujo, texto
//   libre y notas activan su herramienta de anotación de EmbedPDF (ANNOTATION_TOOL).
import { flushSync, mount, unmount } from 'svelte';
import type { IPlugin, PluginRegistry } from '@embedpdf/core';
import { transformRect, type PdfDocumentObject, type PdfPageObject, type Rect, type Rotation, type Size } from '@embedpdf/models';
import type { AnnotationPlugin } from '@embedpdf/plugin-annotation';
import type { DocumentManagerPlugin } from '@embedpdf/plugin-document-manager';
import type { HistoryPlugin } from '@embedpdf/plugin-history';
import type { InteractionManagerPlugin } from '@embedpdf/plugin-interaction-manager';
import type { RenderPlugin } from '@embedpdf/plugin-render';
import { ScrollStrategy } from '@embedpdf/plugin-scroll';
import { SpreadMode, type SpreadPlugin } from '@embedpdf/plugin-spread';
import type { ViewportPlugin } from '@embedpdf/plugin-viewport';
import { ZoomMode, type ZoomLevel, type ZoomPlugin } from '@embedpdf/plugin-zoom';
import { call } from '$lib/api.ts';
import { h } from '$lib/dom.ts';
import type { OcrText, OcrWord } from '$lib/pdf-engine/index.ts';
import { t } from '$texts';
import {
  OTHER_MODE, PAGED, reading, refreshPageText, registry, showPageList, TEXT_MODE, UNIT, VIEWPORT_GAP, ZOOM_MAX, ZOOM_MIN,
  type ViewerScroll,
} from './embed.ts';
import { pageUids } from '../document/pages.ts';
import { MODES, pageStep, type Mode } from './layout.ts';
import PdfPages from './PdfPages.svelte';

export { ZOOM_MAX, ZOOM_MIN } from './embed.ts';

// Herramientas del lienzo (ToolMode en Qt). El lienzo solo implementa la mano; la
// selección de texto y las marcas de texto las gestiona selection.ts (con EmbedPDF); el dibujo,
// el texto libre y las notas, las herramientas de anotación de EmbedPDF (annotations.ts);
// el puntero (seleccionar y transformar anotaciones), la capa de anotaciones de EmbedPDF
// con la barra de editing.ts, y el recorte de OCR, OcrPanel.svelte. El cursor depende de
// `data-tool` (ver viewer.css).
export const TOOLS = {
  HAND: 'hand',
  SELECT: 'select',
  POINTER: 'pointer', // seleccionar, mover y transformar anotaciones
  TEXT: 'text', // texto libre en la página
  NOTE: 'note', // nota adhesiva
  CALLOUT: 'callout', // texto libre con flecha
  HIGHLIGHT: 'highlight',
  UNDERLINE: 'underline',
  STRIKEOUT: 'strikeout',
  SQUIGGLY: 'squiggly', // subrayado ondulado
  INSERT_TEXT: 'insert-text', // marca de inserción con el texto que falta
  REPLACE_TEXT: 'replace-text', // tachado con el texto que lo sustituye
  RECT: 'rect',
  ELLIPSE: 'ellipse',
  LINE: 'line',
  ARROW: 'arrow',
  POLYLINE: 'polyline',
  POLYGON: 'polygon',
  PEN: 'pen',
  MARKER: 'marker', // trazo libre translúcido (rotulador)
  DRAW: 'draw', // trazo fino
  IMAGE: 'image',
  PLACE: 'place', // colocar un sello o una firma: la herramienta de EmbedPDF la pone stamps/
  PLACE_TEXT: 'place-text', // colocar un sello de texto (texto libre): lo hace StampsPanel.svelte
  AREA_OCR: 'area-ocr', // rectángulo para reconocer texto
  REDACT: 'redact', // marcar para censurar: texto (arrastrando sobre él) o un área
} as const;

export type Tool = (typeof TOOLS)[keyof typeof TOOLS];

/** Anotación que crea cada herramienta de texto sobre la selección. */
export type MarkupKind = 'highlight' | 'underline' | 'strikeout' | 'squiggly' | 'insert' | 'replace';

// Herramientas que trabajan sobre la selección de texto (selection.ts) y la anotación que crean.
export const MARKUP_TOOLS: Record<string, MarkupKind> = {
  [TOOLS.HIGHLIGHT]: 'highlight',
  [TOOLS.UNDERLINE]: 'underline',
  [TOOLS.STRIKEOUT]: 'strikeout',
  [TOOLS.SQUIGGLY]: 'squiggly',
  [TOOLS.INSERT_TEXT]: 'insert',
  [TOOLS.REPLACE_TEXT]: 'replace',
};
// Herramientas con las que arrastrar selecciona texto.
export const TEXT_TOOLS = new Set<string>([TOOLS.SELECT, ...Object.keys(MARKUP_TOOLS)]);
// Herramienta de anotación de EmbedPDF de cada herramienta de dibujo (el trazo fino es la
// pluma con otro grosor).
export const ANNOTATION_TOOL: Record<string, string> = {
  [TOOLS.RECT]: 'square',
  [TOOLS.ELLIPSE]: 'circle',
  [TOOLS.LINE]: 'line',
  [TOOLS.ARROW]: 'lineArrow',
  [TOOLS.POLYLINE]: 'polyline',
  [TOOLS.POLYGON]: 'polygon',
  [TOOLS.PEN]: 'ink',
  [TOOLS.MARKER]: 'inkHighlighter',
  [TOOLS.DRAW]: 'ink',
  [TOOLS.TEXT]: 'freeText',
  [TOOLS.CALLOUT]: 'freeTextCallout',
  [TOOLS.NOTE]: 'textComment',
  [TOOLS.IMAGE]: 'stamp',
  [TOOLS.REDACT]: 'redact', // del complemento de censura
};
// Cómo coloca EmbedPDF las páginas en cada modo de vista.
const LAYOUTS: Record<Mode, { strategy: string; spread: SpreadMode }> = {
  [MODES.CONTINUOUS]: { strategy: ScrollStrategy.Vertical, spread: SpreadMode.None },
  [MODES.SINGLE]: { strategy: PAGED, spread: SpreadMode.None },
  [MODES.DOUBLE]: { strategy: PAGED, spread: SpreadMode.Odd },
};
const ZOOM_STEP = 1.25;
const WHEEL_NOTCH = 100; // deltaY de un paso de la rueda del ratón
const THUMB_BOX = [230, 290]; // px de la miniatura (115×145 en pantalla, a doble densidad)
const WHEEL_FLIP_COOLDOWN = 350; // ms entre cambios de página con la rueda (modo paginado)

const ANNOTATION_LAYER = '#annotation-layer'; // capa de anotaciones de EmbedPDF (PdfPage.svelte)
const ANNOTATION = `${ANNOTATION_LAYER} > *`; // sus elementos
const sameKeys = (a: string[] | null, b: string[]) => a?.length === b.length && a.every((key, i) => key === b[i]);

/** Tamaño de la página tal como se ve, en puntos (EmbedPDF lo da sin girar). */
export function shownSize({ size, rotation }: PdfPageObject): [number, number] {
  const round = (value: number) => Math.round(value * 100) / 100;
  return rotation % 2 ? [round(size.height), round(size.width)] : [round(size.width), round(size.height)];
}

/** Rectángulo `[x0, y0, x1, y1]` en puntos de la página tal como se ve. */
export type Box = [number, number, number, number];

/** Rectángulo de la página en la ventana (como un DOMRect). */
export interface ClientBox {
  left: number;
  top: number;
  width: number;
  height: number;
  right: number;
  bottom: number;
}

/** Avisos del lienzo al visor. */
export interface CanvasEvents {
  onPage?(index: number): void;
  onZoom?(zoom: number): void;
  onMode?(mode: Mode): void;
  /** Se va a activar la herramienta `tool` (para darle su estilo). */
  onTool?(tool: string, documentId: string): void;
  /** Se puso a la vista una versión nueva del documento. */
  onDocument?(documentId: string): void;
}

/** Una versión del documento que da Python para abrirla en EmbedPDF (viewer.document_url). */
interface DocumentVersion {
  url: string;
  keys: string[]; // la clave de cada página
  password: string | null;
  ocr: { index: number; words: OcrWord[] }[]; // las palabras del OCR de cada página que las tiene
}

/** Al montarse una página: (página, documento) → lo que se llama al desmontarla. */
type MountHook = (index: number, documentId: string | null) => (() => void) | undefined | void;

/** Lo que exporta PdfPages.svelte. */
interface PagesComponent {
  show(documentId: string): void;
}

export class PageCanvas {
  docId: number;
  events: CanvasEvents;
  zoom = 1;
  level: ZoomLevel = UNIT; // nivel de zoom de EmbedPDF: escala (px por punto) o un modo de ajuste
  mode: Mode = MODES.CONTINUOUS;
  tool: string = TOOLS.SELECT;
  current = 0;
  closed = false;

  registry: PluginRegistry | null = null;
  shown: string | null = null; // id en EmbedPDF del documento a la vista
  shownKeys: string[] | null = null; // claves de página de esa versión
  password: string | null = null; // la de esa versión, si está cifrada
  ocrPages = new Set<number>(); // `uid` de las páginas que llevan el texto del OCR (invisible)
  ready = false; // EmbedPDF ya colocó sus páginas
  target = { index: 0, atBottom: false }; // adónde ir en cuanto se pueda
  mounted = new Map<number, HTMLElement>(); // página -> capa enganchada a una página montada
  mountHooks: MountHook[] = []; // al montarse cada página
  unsubscribe: (() => void)[] = []; // avisos del registro (se quitan al cerrar)
  seq = 0;
  lastFlip = 0;
  sizes!: [number, number][];
  keys!: string[];
  slots!: HTMLElement[];
  pages: (PagesComponent & Record<string, unknown>) | null = null;
  el: HTMLDivElement;
  loading: Promise<void>;

  /**
   * `docId`: documento del servicio "viewer"; `sizes`: tamaño de cada página en puntos; `keys`:
   * clave de cada página (cambia cuando cambia su imagen).
   */
  constructor(docId: number, sizes: [number, number][], keys: string[], events: CanvasEvents = {}) {
    this.docId = docId;
    this.events = events;
    this.el = h('div', { class: 'pdf-canvas', tabindex: '0', dataset: { tool: this.tool }, style: { padding: `${VIEWPORT_GAP}px` } });
    this._setSlots(sizes, keys);

    this.el.addEventListener('wheel', (ev) => this._onWheel(ev), { passive: false });
    this._enablePanning();
    this.loading = this._start().catch((err) => this._fail(err));
  }

  /** Complemento `id` del registro (ya listo: solo se pide después de `loading`). */
  _plugin<T extends IPlugin>(id: string): T {
    return this.registry!.getPlugin<T>(id)!;
  }

  _scrollPlugin(): ViewerScroll {
    return this.registry!.getPlugin('scroll') as unknown as ViewerScroll;
  }

  /**
   * Páginas de una versión del documento que da Python (`keys`: la clave de cada una). Si no es
   * la que se ve (la cambió Python: censura, OCR), se vuelve a abrir en EmbedPDF.
   */
  setPages(sizes: [number, number][], keys: string[]): void {
    if (sameKeys(this.keys, keys) && sameKeys(this.shownKeys, keys)) {
      this.sizes = sizes;
      return;
    }
    this._setSlots(sizes, keys);
    this.current = Math.min(this.current, this.pageCount - 1);
    if (this.registry && !sameKeys(this.shownKeys, keys)) this.loading = this._load().catch((err) => this._fail(err));
  }

  /** El documento a la vista tal como lo tiene EmbedPDF (para las operaciones del motor). */
  get documentObject(): PdfDocumentObject | null {
    return this.shown ? this._documentOf(this.shown) : null;
  }

  _documentOf(documentId: string): PdfDocumentObject | null {
    return this.registry?.getStore().getState().core.documents[documentId]?.document ?? null;
  }

  /** Como `documentObject`, pero falla si aún no hay ninguno a la vista. */
  shownDocument(): PdfDocumentObject {
    const doc = this.documentObject;
    if (!doc) throw new Error(t.viewer.document.notShown);
    return doc;
  }

  /**
   * Muestra `pages`, las páginas que tiene ahora en el motor el documento a la vista (tras
   * girar, mover, insertar…: document/pages.ts), sin volver a abrirlo. `keys`: la clave de cada una.
   */
  showPages(pages: PdfPageObject[], keys: string[]): void {
    const id = this.shown!;
    showPageList(this.registry!, id, pages);
    // Como al volver a abrirlo, el historial de EmbedPDF empieza de nuevo: Ctrl+Z deshace
    // primero lo que hay en él y después las operaciones de página (ver Viewer.svelte).
    this._plugin<HistoryPlugin>('history').provides().forDocument(id).purgeByMetadata(() => true);
    // Las capas de cada página se conservan (son por posición; las vuelve a dibujar cada módulo).
    const slots = pages.map((_, i) => this.slots[i] ?? h('div', { class: 'pdf-page__layers' }));
    Object.assign(this, { sizes: pages.map(shownSize), keys, shownKeys: keys, slots });
    this.current = Math.min(this.current, this.pageCount - 1);
  }

  /**
   * Escribe en el documento a la vista las palabras del OCR (texto invisible, para seleccionarlas
   * y buscarlas) y hace que EmbedPDF vuelva a leer esas páginas.
   */
  async writeOcrText(pages: OcrText[]): Promise<void> {
    const id = this.shown;
    const changed = await (await reading()).writeOcrText(this.shownDocument(), pages);
    if (id !== this.shown) return; // llegó otra versión, que ya trae ese texto de Python
    this._addOcrPages(pages, this.keys);
    if (changed.length) refreshPageText(this.registry!, id!, changed);
  }

  /** Apunta qué páginas llevan el texto del OCR (las copias que salen del visor se lo quitan). */
  _addOcrPages(pages: OcrText[], keys: string[]): void {
    const uids = pageUids(keys);
    for (const { index, words } of pages) {
      if (words.length) this.ocrPages.add(uids[index]);
    }
  }

  /**
   * Termina la edición en curso en la página (texto libre de EmbedPDF): lo escrito se guarda
   * al perder el foco. EmbedPDF solo deja de editar con un clic en el fondo de la página (y
   * entonces quita también la selección): se le da ese clic. Si no, el cuadro seguía
   * admitiendo texto sin guardarlo.
   */
  finishEditing(): void {
    const editor = this.el.querySelector(`${ANNOTATION_LAYER} [contenteditable="true"]`);
    // La capa para el clic (mientras edita en esa página): no llega a las demás herramientas.
    editor?.closest('.pdf-page__pointer')?.dispatchEvent(new PointerEvent('pointerdown', { button: 0, isPrimary: true }));
    if (this.el.contains(document.activeElement)) (document.activeElement as HTMLElement).blur();
  }

  /**
   * `hook(index, documentId)` se llama al montar EmbedPDF cada página del documento a la vista;
   * lo que devuelva se llama al desmontarla.
   */
  onPageMount(hook: MountHook): void {
    this.mountHooks.push(hook);
  }

  _setSlots(sizes: [number, number][], keys: string[]): void {
    this.sizes = sizes;
    this.keys = keys;
    this.slots = sizes.map(() => h('div', { class: 'pdf-page__layers' }));
  }

  destroy(): void {
    this.closed = true;
    for (const off of this.unsubscribe) off();
    if (this.pages) unmount(this.pages);
    // El registro es de toda la app: se cierra el documento de este visor (uno que aún se
    // esté cargando lo cierra _load al terminar). Se aplaza: destroy() corre mientras Svelte
    // desmonta la pestaña y cerrar ahora cambia el estado de EmbedPDF en mitad de ese cambio
    // (la pestaña siguiente no llegaba a mostrarse).
    const { registry: embed, shown } = this;
    if (embed && shown) setTimeout(() => embed.getPlugin<DocumentManagerPlugin>('document-manager')!.provides().closeDocument(shown));
  }

  get paged(): boolean {
    return this.mode !== MODES.CONTINUOUS;
  }

  get pageCount(): number {
    return this.sizes.length;
  }

  /** Miniaturas { página: url blob: } de la versión actual (liberarlas con `release`). */
  async thumbnails(pages: number[]): Promise<Record<number, string>> {
    await this.loading;
    const id = this.shown;
    if (!id || !sameKeys(this.shownKeys, this.keys)) return {};
    const render = this._plugin<RenderPlugin>('render').provides().forDocument(id);
    const result: Record<number, string> = {};
    for (const index of pages) {
      const [w, h] = this.sizes[index] ?? [];
      if (!w) continue;
      const scale = Math.min(THUMB_BOX[0] / w, THUMB_BOX[1] / h);
      // EmbedPDF dibuja sin girar si no se le pasa el giro de la página. Con las anotaciones:
      // en el lienzo las dibuja su capa, pero la miniatura es una sola imagen.
      const { rotation } = this.pageInfo(index);
      const options = { scaleFactor: scale, rotation, dpr: 1, imageQuality: 0.8, withAnnotations: true };
      const blob = await render.renderPage({ pageIndex: index, options }).toPromise();
      result[index] = URL.createObjectURL(blob);
    }
    return result;
  }

  /** Página `index` del documento a la vista según EmbedPDF: `{ size }` sin girar y `rotation` (cuartos de vuelta). */
  pageInfo(index: number): { size: Size; rotation: Rotation } {
    const page = this.shown ? this.registry?.getStore().getState().core.documents[this.shown]?.document?.pages[index] : undefined;
    return page ?? { size: { width: this.sizes[index][0], height: this.sizes[index][1] }, rotation: 0 as Rotation };
  }

  /** Rectángulo de EmbedPDF (página sin girar) → `[x0, y0, x1, y1]` en puntos de la página tal como se ve. */
  toView(index: number, rect: Rect): Box {
    const { size, rotation } = this.pageInfo(index);
    const r = transformRect(size, rect, rotation, 1);
    return [r.origin.x, r.origin.y, r.origin.x + r.size.width, r.origin.y + r.size.height];
  }

  /** Lo contrario de `toView`: `[x0, y0, x1, y1]` de la página tal como se ve → rectángulo de EmbedPDF. */
  toPage(index: number, [x0, y0, x1, y1]: Box): Rect {
    const { size, rotation } = this.pageInfo(index);
    const shown = rotation % 2 ? { width: size.height, height: size.width } : size;
    return transformRect(shown, { origin: { x: x0, y: y0 }, size: { width: x1 - x0, height: y1 - y0 } }, ((4 - rotation) % 4) as Rotation, 1);
  }

  // ── Zoom ───────────────────────────────────────────────────────────────
  zoomIn(): void {
    this.setZoom(this.zoom * ZOOM_STEP);
  }

  zoomOut(): void {
    this.setZoom(this.zoom / ZOOM_STEP);
  }

  /** Cambia el zoom manteniendo fijo el punto bajo `anchor` (coordenadas de la ventana). */
  setZoom(factor: number, anchor: { x: number; y: number } | null = null): void {
    const zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, factor));
    const box = this.el.getBoundingClientRect();
    this._requestZoom(zoom * UNIT, anchor ? { vx: anchor.x - box.left, vy: anchor.y - box.top } : undefined);
  }

  /** Ajustes que se mantienen al cambiar el tamaño de la ventana (EmbedPDF los recalcula). */
  fitWidth(): void {
    this._requestZoom(ZoomMode.FitWidth);
    this.scrollToPage(this.current);
  }

  fitPage(): void {
    this._requestZoom(ZoomMode.FitPage);
    this.scrollToPage(this.current);
  }

  _requestZoom(level: ZoomLevel, center?: { vx: number; vy: number }): void {
    this.level = level;
    if (this.ready) this._zoomScope().requestZoom(level, center);
    else if (typeof level === 'number') this._zoomChanged(level);
  }

  _zoomScope() {
    return this._plugin<ZoomPlugin>('zoom').provides().forDocument(this.shown!);
  }

  _zoomChanged(scale: number): void {
    this.zoom = scale / UNIT;
    this.events.onZoom?.(this.zoom);
  }

  // ── Modos de vista y navegación ────────────────────────────────────────
  setMode(mode: Mode): void {
    if (mode === this.mode) return;
    const anchor = this.current;
    this.mode = mode;
    if (this.shown) this._applyMode(this.shown);
    this.scrollToPage(anchor);
    this.events.onMode?.(mode);
  }

  _applyMode(id: string): void {
    const { strategy, spread } = LAYOUTS[this.mode];
    this._plugin<SpreadPlugin>('spread').provides().forDocument(id).setSpreadMode(spread);
    // La estrategia paginada es nuestra (embed.ts): EmbedPDF no la tiene en su lista.
    this._scrollPlugin().provides().forDocument(id).setScrollStrategy(strategy as ScrollStrategy);
  }

  step(): number {
    return pageStep(this.mode);
  }

  /** Lleva la página `index` a la vista (centrada, o su borde superior si no cabe). */
  scrollToPage(index: number, atBottom = false): void {
    if (index < 0 || index >= this.pageCount) return;
    if (!this._live()) {
      this.target = { index, atBottom };
      this._setCurrent(index, true);
      return;
    }
    this._showRow(index);
    const r = this._viewRect(index);
    const vw = this.el.clientWidth;
    const vh = this.el.clientHeight;
    const top = r.h <= vh ? r.y + r.h / 2 - vh / 2 : atBottom ? r.y + r.h + 12 - vh : r.y - 12;
    this._scrollTo(r.x + r.w / 2 - vw / 2, top);
    this._setCurrent(index, true);
  }

  setNight(enabled: boolean): void {
    this.el.classList.toggle('is-night', enabled);
  }

  setTool(tool: string): void {
    this.tool = tool;
    this.el.dataset.tool = tool;
    if (this.shown) this._applyTool(this.shown);
  }

  _applyTool(id: string): void {
    // Activar una herramienta de anotación cambia el modo del gestor de interacción (y quitarla
    // vuelve al predeterminado, el de texto).
    if (this.tool === TOOLS.PLACE) return; // ya la activó stamps/ (activateStampPlacement…)
    const annotationTool = ANNOTATION_TOOL[this.tool];
    const annotation = this._plugin<AnnotationPlugin>('annotation').provides().forDocument(id);
    if (annotationTool) {
      this.events.onTool?.(this.tool, id);
      annotation.setActiveTool(annotationTool);
      return;
    }
    if (annotation.getActiveTool()) annotation.setActiveTool(null);
    const mode = TEXT_TOOLS.has(this.tool) ? TEXT_MODE : OTHER_MODE;
    const interaction = this._plugin<InteractionManagerPlugin>('interaction-manager').provides().forDocument(id);
    if (interaction.getActiveMode() !== mode) interaction.activate(mode);
  }

  /**
   * Hace del documento a la vista el activo de EmbedPDF. Se abren sin activarlos (cada visor usa
   * `forDocument`), pero plugin-stamp y plugin-signature ponen su herramienta en el activo, sea
   * cual sea el documento que se les pida: sin esto iba al primero que se abrió.
   */
  activate(): void {
    this._plugin<DocumentManagerPlugin>('document-manager').provides().setActiveDocument(this.shown!);
  }

  /** Centra en la vista el rectángulo `[x0, y0, x1, y1]` (puntos) de la página `index`. */
  scrollToRect(index: number, [x0, y0, x1, y1]: Box): void {
    if (!this._live()) {
      this.scrollToPage(index);
      return;
    }
    this._showRow(index);
    const r = this._viewRect(index);
    const [pw, ph] = this.sizes[index];
    this._scrollTo(
      r.x + ((x0 + x1) / 2 / pw) * r.w - this.el.clientWidth / 2,
      r.y + ((y0 + y1) / 2 / ph) * r.h - this.el.clientHeight / 2,
    );
    this._setCurrent(index);
  }

  /** La vista muestra la versión actual del documento y ya tiene sus páginas colocadas. */
  _live(): boolean {
    return this.ready && sameKeys(this.shownKeys, this.keys);
  }

  /** En modo paginado, pasa a la fila (página o par) de `index`. */
  _showRow(index: number): void {
    if (!this.paged) return;
    const { virtualItems } = this._scroll().getLayout();
    const row = virtualItems.find((item) => item.pageNumbers.includes(index + 1));
    if (!row) return;
    this._scrollPlugin().showRow(this.shown!, row.index);
    flushSync(); // que el Scroller ya mida lo que la fila nueva
  }

  _scroll() {
    return this._scrollPlugin().provides().forDocument(this.shown!);
  }

  /** EmbedPDF aplica los desplazamientos en el siguiente fotograma: así no se pisan con los suyos. */
  _scrollTo(x: number, y: number): void {
    this._plugin<ViewportPlugin>('viewport').provides().forDocument(this.shown!).scrollTo({ x, y, behavior: 'instant' });
  }

  // ── Coordenadas y marcas ───────────────────────────────────────────────
  /** Página bajo (o más cerca de) un punto de la ventana y ese punto en puntos PDF. */
  pageAt(clientX: number, clientY: number): { index: number; x: number; y: number } | null {
    let best: { index: number; box: DOMRect; dist: number } | null = null;
    for (const [i, slot] of this.mounted) {
      const box = slot.getBoundingClientRect();
      const dx = Math.max(box.left - clientX, 0, clientX - box.right);
      const dy = Math.max(box.top - clientY, 0, clientY - box.bottom);
      const dist = dy * 1e6 + dx; // primero la página a esa altura
      if (!best || dist < best.dist) best = { index: i, box, dist };
    }
    if (!best) return null;
    const [pw, ph] = this.sizes[best.index];
    const { box } = best;
    return { index: best.index, x: ((clientX - box.left) / box.width) * pw, y: ((clientY - box.top) / box.height) * ph };
  }

  /** Un punto de la ventana en puntos PDF de la página `index` (aunque caiga fuera de ella). */
  pointOn(index: number, clientX: number, clientY: number): [number, number] {
    const box = this.pageRect(index);
    const [pw, ph] = this.sizes[index];
    return [((clientX - box.left) / box.width) * pw, ((clientY - box.top) / box.height) * ph];
  }

  /** Capa de marcas de la página `index` (se crea al pedirla; se pierde con `setPages`). */
  marks(index: number): HTMLElement {
    const slot = this.slots[index];
    return slot.querySelector<HTMLElement>(':scope > .pdf-page__marks') ?? slot.appendChild(h('div', { class: 'pdf-page__marks' }));
  }

  /** Añade a la página `index` un rectángulo `[x0, y0, x1, y1]` en puntos con la clase `className`. */
  addMark(index: number, [x0, y0, x1, y1]: Box | number[], className: string): HTMLDivElement {
    const [pw, ph] = this.sizes[index];
    const mark = h('div', {
      class: className,
      style: {
        left: `${(x0 / pw) * 100}%`,
        top: `${(y0 / ph) * 100}%`,
        width: `${((x1 - x0) / pw) * 100}%`,
        height: `${((y1 - y0) / ph) * 100}%`,
      },
    });
    this.marks(index).append(mark);
    return mark;
  }

  /** Elementos de las capas de todas las páginas (también de las que no están montadas). */
  queryAll(selector: string): HTMLElement[] {
    return this.slots.flatMap((slot) => [...slot.querySelectorAll<HTMLElement>(selector)]);
  }

  /** Rectángulo de la página `index` en la ventana, esté montada o no. */
  pageRect(index: number): ClientBox {
    const slot = this.slots[index];
    if (slot.isConnected || !this.ready) return slot.getBoundingClientRect();
    const r = this._viewRect(index);
    const box = this.el.getBoundingClientRect();
    const left = box.left + this.el.clientLeft + r.x - this.el.scrollLeft;
    const top = box.top + this.el.clientTop + r.y - this.el.scrollTop;
    return { left, top, width: r.w, height: r.h, right: left + r.w, bottom: top + r.h };
  }

  /** Rectángulo de la página `index` en píxeles del contenedor con scroll (según EmbedPDF). */
  _viewRect(index: number): { x: number; y: number; w: number; h: number } {
    const { virtualItems, totalContentSize } = this._scroll().getLayout();
    const item = virtualItems.find((it) => it.pageNumbers.includes(index + 1))!;
    const page = item.pageLayouts.find((p) => p.pageIndex === index)!;
    const z = this.zoom * UNIT;
    // El contenido se centra si es más pequeño que la vista (ver .pdf-canvas__inner), y cada fila dentro de él.
    const freeX = Math.max(0, this.el.clientWidth - 2 * VIEWPORT_GAP - totalContentSize.width * z);
    const freeY = Math.max(0, this.el.clientHeight - 2 * VIEWPORT_GAP - totalContentSize.height * z);
    const centered = Math.max(0, (totalContentSize.width - item.width) / 2);
    return {
      x: VIEWPORT_GAP + freeX / 2 + (item.x + centered + page.x) * z,
      y: VIEWPORT_GAP + freeY / 2 + (item.y + page.y) * z,
      w: page.rotatedWidth * z,
      h: page.rotatedHeight * z,
    };
  }

  _setCurrent(index: number, force = false): void {
    if (index === this.current && !force) return;
    this.current = index;
    this.events.onPage?.(index);
  }

  // ── EmbedPDF ───────────────────────────────────────────────────────────
  async _start(): Promise<void> {
    const embed = await registry();
    if (this.closed) return;
    this._connect(embed);
    this.pages = mount(PdfPages, {
      target: this.el,
      props: { element: this.el, overlay: (index: number) => (page: HTMLElement) => this._attach(index, page) },
    }) as unknown as PagesComponent & Record<string, unknown>;
    await this._load();
  }

  /** Avisos del registro (compartido por todos los visores): solo los de nuestro documento. */
  _connect(embed: PluginRegistry): void {
    this.registry = embed;
    const scroll = this._scrollPlugin().provides();
    const zoom = this._plugin<ZoomPlugin>('zoom').provides();
    const viewport = this._plugin<ViewportPlugin>('viewport').provides();
    this.unsubscribe = [
      scroll.onPageChange(({ documentId, pageNumber }) => {
        if (documentId === this.shown && this._live()) this._setCurrent(pageNumber - 1);
      }),
      zoom.onStateChange(({ documentId, state }) => {
        if (documentId === this.shown) this._zoomChanged(state.currentZoomLevel);
      }),
      // Un documento recién abierto espera (gate) a que se fije el zoom, y eso necesita
      // que la vista ya tenga tamaño: se fija en cuanto lo tiene.
      viewport.onViewportResize(({ documentId }) => {
        if (documentId === this.shown && viewport.isGated(documentId)) this._zoomScope().requestZoom(this.level);
      }),
      scroll.onLayoutReady(({ documentId, isInitial }) => {
        if (documentId !== this.shown || !isInitial) return;
        this.ready = true;
        // Tras el desplazamiento con el que EmbedPDF coloca el documento (en este fotograma).
        requestAnimationFrame(() => {
          if (this._live()) this.scrollToPage(this.target.index, this.target.atBottom);
        });
      }),
    ];
  }

  /** Abre en EmbedPDF la versión del documento que tiene Python y la pone a la vista. */
  async _load(): Promise<void> {
    const seq = ++this.seq;
    const { url, keys, password, ocr } = await call<DocumentVersion>('viewer.document_url', this.docId);
    const response = await fetch(url);
    if (!response.ok) throw new Error(t.viewer.canvas.downloadError(response.status));
    const buffer = await response.arrayBuffer();
    if (this.closed || seq !== this.seq) return; // llegó otra versión más nueva
    this.password = password;
    const docs = this._plugin<DocumentManagerPlugin>('document-manager').provides();
    const { documentId, task } = await docs.openDocumentBuffer({
      buffer, name: `documento-${this.docId}.pdf`, documentId: `viewer-${this.docId}-${seq}`, autoActivate: false,
      password: password ?? undefined,
      // Los permisos del PDF los comprueba Python al guardar, como con cualquier otro.
      permissions: { enforceDocumentPermissions: false },
    }).toPromise();
    await task.toPromise();
    // El texto del OCR que guarda Python, antes de que EmbedPDF lea las páginas. Si fallara, el
    // documento se ve igual (sin poder seleccionar ese texto).
    const text: OcrText[] = ocr.map(({ index, words }) => ({ index, words, replace: false }));
    const opened = this._documentOf(documentId);
    if (text.length && opened && !this.closed && seq === this.seq) {
      await (await reading()).writeOcrText(opened, text).catch((err) => console.error('No se pudo escribir el texto del OCR', err));
    }
    if (this.closed || seq !== this.seq) {
      docs.closeDocument(documentId);
      return;
    }
    if (this._live()) this.target = { index: this.current, atBottom: false };
    const previous = this.shown;
    this.finishEditing(); // mientras el documento anterior sigue abierto
    Object.assign(this, { shown: documentId, shownKeys: keys, ready: false, ocrPages: new Set<number>() });
    this._addOcrPages(text, keys);
    this._applyMode(documentId);
    this._applyTool(documentId);
    this.pages!.show(documentId);
    flushSync(); // la vista suelta el documento anterior antes de cerrarlo
    if (previous) docs.closeDocument(previous);
    this.events.onDocument?.(documentId);
  }

  /** Engancha la capa de la página `index` a su página montada por EmbedPDF. */
  _attach(index: number, page: HTMLElement): (() => void) | undefined {
    const slot = this.slots[index];
    if (!slot) return undefined;
    page.append(slot);
    this.mounted.set(index, slot);
    const cleanups = this.mountHooks.map((hook) => hook(index, this.shown));
    return () => {
      for (const cleanup of cleanups) cleanup?.();
      slot.remove();
      if (this.mounted.get(index) === slot) this.mounted.delete(index);
    };
  }

  _fail(err: unknown): void {
    if (this.closed) return;
    console.error('No se pudo mostrar el documento con EmbedPDF', err);
    this.el.replaceChildren(h('p', { class: 'pdf-canvas__error' }, t.viewer.canvas.error));
  }

  // ── Ratón: rueda (zoom con Ctrl, pasar página en modo paginado), clics y arrastre ──
  // El pellizco es del zoom de EmbedPDF (ZoomGestureWrapper).
  _onWheel(ev: WheelEvent): void {
    if (ev.ctrlKey) {
      ev.preventDefault();
      // Un paso de la rueda del ratón (100) es un paso de zoom; el trackpad da pasos más finos.
      if (ev.deltaY) this.setZoom(this.zoom * ZOOM_STEP ** (-ev.deltaY / WHEEL_NOTCH), { x: ev.clientX, y: ev.clientY });
      return;
    }
    if (this.paged && ev.deltaY && this._wheelFlip(ev.deltaY > 0)) ev.preventDefault();
  }

  /** Como en Adobe: primero se desplaza dentro de la página y solo en el borde pasa de página. */
  _wheelFlip(down: boolean): boolean {
    const el = this.el;
    const atEdge = down ? el.scrollTop + el.clientHeight >= el.scrollHeight - 1 : el.scrollTop <= 0;
    if (!atEdge) return false;
    const now = performance.now();
    if (now - this.lastFlip < WHEEL_FLIP_COOLDOWN) return true; // absorbe la inercia del trackpad
    const step = this.step();
    const base = Math.floor(this.current / step) * step;
    const target = down ? base + step : base - step;
    if (target < 0 || target >= this.pageCount) return false;
    this.lastFlip = now;
    this.scrollToPage(target, !down);
    return true;
  }

  /** Herramienta mano: arrastrar con el botón izquierdo desplaza el documento. */
  _enablePanning(): void {
    let start: { x: number; y: number; left: number; top: number } | null = null;
    this.el.addEventListener('pointerdown', (ev) => {
      const box = this.el.getBoundingClientRect();
      const onScrollbar = ev.clientX - box.left >= this.el.clientWidth || ev.clientY - box.top >= this.el.clientHeight;
      // Con el dedo desplaza el navegador. Sobre una anotación, el arrastre es suyo (moverla).
      if (ev.pointerType === 'touch' || ev.button !== 0 || onScrollbar || this.tool !== TOOLS.HAND || (ev.target as Element | null)?.closest?.(ANNOTATION)) return;
      start = { x: ev.clientX, y: ev.clientY, left: this.el.scrollLeft, top: this.el.scrollTop };
      this.el.setPointerCapture(ev.pointerId);
      this.el.classList.add('is-panning');
    });
    this.el.addEventListener('pointermove', (ev) => {
      if (!start) return;
      this.el.scrollLeft = start.left - (ev.clientX - start.x);
      this.el.scrollTop = start.top - (ev.clientY - start.y);
    });
    const stop = () => {
      start = null;
      this.el.classList.remove('is-panning');
    };
    this.el.addEventListener('pointerup', stop);
    this.el.addEventListener('pointercancel', stop);
  }
}
