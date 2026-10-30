// Lienzo del visor: las páginas con zoom, modos de vista y modo noche (equivale a
// src_qt/ui/viewer/canvas/view.py). Desde el paso 2 de docs/web/embedpdf.md las páginas,
// el scroll, el zoom y el mosaico son de EmbedPDF (embed.js, PdfPages.svelte); esta
// clase da al resto del visor la misma API que antes. El registro de EmbedPDF es uno para
// toda la app: cada visor abre en él su documento y solo atiende los avisos de ese documento.
//
// - Python es el dueño de las páginas: cuando cambian (girar, mover, insertar, censurar…) se
//   vuelve a abrir en EmbedPDF la versión que él tiene (`viewer.document_url`). Mientras se
//   carga, la vista sigue con la anterior. Las anotaciones, en cambio, las edita EmbedPDF en
//   su copia (annotations.js las pasa a Python antes de cada operación).
// - Cada página tiene una capa del visor (`slots[i]`) donde otros módulos dibujan en
//   porcentaje de la página las marcas (`marks(i)`) de selección, búsqueda, OCR o censura.
//   Las capas existen siempre, aunque EmbedPDF solo monte las páginas a la vista; se
//   enganchan a la página al montarse.
// - `el` es el contenedor con scroll (la vista de EmbedPDF): ahí escuchan el ratón los
//   demás módulos. La selección de texto es de EmbedPDF (text.js): está activa con las
//   herramientas de texto (modo TEXT_MODE del gestor de interacción). Las de dibujo, texto
//   libre y notas activan su herramienta de anotación de EmbedPDF (ANNOTATION_TOOL).
import { flushSync, mount, unmount } from 'svelte';
import { refreshPages } from '@embedpdf/core';
import { transformRect } from '@embedpdf/models';
import { ScrollStrategy } from '@embedpdf/plugin-scroll';
import { SpreadMode } from '@embedpdf/plugin-spread';
import { ZoomMode } from '@embedpdf/plugin-zoom';
import { call } from '$lib/api.js';
import { h } from '$lib/dom.js';
import { OTHER_MODE, PAGED, registry, TEXT_MODE, UNIT, VIEWPORT_GAP, ZOOM_MAX, ZOOM_MIN } from './embed.js';
import { MODES, pageStep } from './layout.js';
import PdfPages from './PdfPages.svelte';

export { ZOOM_MAX, ZOOM_MIN } from './embed.js';

// Herramientas del lienzo (ToolMode en Qt). El lienzo solo implementa la mano; la
// selección de texto y las marcas de texto las gestiona text.js (con EmbedPDF); el dibujo,
// el texto libre y las notas, las herramientas de anotación de EmbedPDF (annotations.js);
// el puntero (seleccionar y transformar anotaciones), la capa de anotaciones de EmbedPDF
// con la barra de editing.js, y el recorte de OCR, OcrPanel.svelte. El cursor depende de
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
  AREA_OCR: 'area-ocr', // rectángulo para reconocer texto
  REDACT: 'redact', // marcar para censurar: texto (arrastrando sobre él) o un área
};
// Herramientas que trabajan sobre la selección de texto (text.js) y la anotación que crean.
export const MARKUP_TOOLS = {
  [TOOLS.HIGHLIGHT]: 'highlight',
  [TOOLS.UNDERLINE]: 'underline',
  [TOOLS.STRIKEOUT]: 'strikeout',
  [TOOLS.SQUIGGLY]: 'squiggly',
  [TOOLS.INSERT_TEXT]: 'insert',
  [TOOLS.REPLACE_TEXT]: 'replace',
};
// Herramientas con las que arrastrar selecciona texto.
export const TEXT_TOOLS = new Set([TOOLS.SELECT, ...Object.keys(MARKUP_TOOLS)]);
// Herramienta de anotación de EmbedPDF de cada herramienta de dibujo (el trazo fino es la
// pluma con otro grosor).
export const ANNOTATION_TOOL = {
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
const LAYOUTS = {
  [MODES.CONTINUOUS]: { strategy: ScrollStrategy.Vertical, spread: SpreadMode.None },
  [MODES.SINGLE]: { strategy: PAGED, spread: SpreadMode.None },
  [MODES.DOUBLE]: { strategy: PAGED, spread: SpreadMode.Odd },
};
const ZOOM_STEP = 1.25;
const WHEEL_NOTCH = 100; // deltaY de un paso de la rueda del ratón
const THUMB_BOX = [230, 290]; // px de la miniatura (115×145 en pantalla, a doble densidad)
const PRINT_QUALITY = 0.9; // JPEG de las páginas para imprimir
const WHEEL_FLIP_COOLDOWN = 350; // ms entre cambios de página con la rueda (modo paginado)

const ANNOTATION_LAYER = '#annotation-layer'; // capa de anotaciones de EmbedPDF (PdfPage.svelte)
const ANNOTATION = `${ANNOTATION_LAYER} > *`; // sus elementos
const sameKeys = (a, b) => a?.length === b.length && a.every((key, i) => key === b[i]);

export class PageCanvas {
  /**
   * @param {number} docId documento del servicio "viewer"
   * @param {Array<[number, number]>} sizes tamaño de cada página en puntos
   * @param {string[]} keys clave de cada página (cambia cuando cambia su imagen)
   * @param {{ onPage?: (i) => void, onZoom?: (z) => void, onMode?: (m) => void,
   *   onTool?: (tool, documentId) => void, onDocument?: (documentId) => void }} events
   *   `onTool`: se va a activar la herramienta `tool` (para darle su estilo); `onDocument`:
   *   se puso a la vista una versión nueva del documento.
   */
  constructor(docId, sizes, keys, events = {}) {
    this.docId = docId;
    this.events = events;
    this.zoom = 1;
    this.level = UNIT; // nivel de zoom de EmbedPDF: escala (px por punto) o un modo de ajuste
    this.mode = MODES.CONTINUOUS;
    this.tool = TOOLS.SELECT;
    this.current = 0;
    this.closed = false;

    this.shown = null; // id en EmbedPDF del documento a la vista
    this.shownKeys = null; // claves de página de esa versión
    this.ready = false; // EmbedPDF ya colocó sus páginas
    this.target = { index: 0, atBottom: false }; // adónde ir en cuanto se pueda
    this.mounted = new Map(); // página -> capa enganchada a una página montada
    this.mountHooks = []; // (página, documento) => limpieza, al montarse cada página
    this.seq = 0;
    this.lastFlip = 0;

    this.el = h('div', { class: 'pdf-canvas', tabindex: '0', dataset: { tool: this.tool }, style: { padding: `${VIEWPORT_GAP}px` } });
    this._setSlots(sizes, keys);

    this.el.addEventListener('wheel', (ev) => this._onWheel(ev), { passive: false });
    this._enablePanning();
    this.loading = this._start().catch((err) => this._fail(err));
  }

  /** Nuevas páginas tras una operación (rotar, insertar, mover…); el llamador elige a cuál ir. */
  setPages(sizes, keys) {
    if (this._turnInPlace(sizes, keys)) return;
    this._setSlots(sizes, keys);
    this.current = Math.min(this.current, this.pageCount - 1);
    if (this.registry && !sameKeys(this.shownKeys, keys)) this.loading = this._load().catch((err) => this._fail(err));
  }

  /**
   * Si solo cambió el giro de algunas páginas (la clave `xref:giro:revisión`), se giran sin
   * volver a cargar el documento en EmbedPDF, que costaba casi un segundo y una copia más del
   * PDF en memoria. EmbedPDF abre los documentos con el giro aparte («normalizado»): todo lo
   * calcula en la página sin girar y el giro solo lo usa para mostrarla, así que basta con
   * cambiarlo en su estado, redibujar esas páginas y recolocar las demás. Devuelve si lo hizo.
   */
  _turnInPlace(sizes, keys) {
    const id = this.shown;
    if (!id || !sameKeys(this.shownKeys, this.keys) || keys.length !== this.keys.length) return false;
    const turns = new Map();
    for (const [i, key] of keys.entries()) {
      const [xref, rotation, revision] = key.split(':');
      const [oldXref, oldRotation, oldRevision] = this.keys[i].split(':');
      if (xref !== oldXref || revision !== oldRevision) return false;
      if (rotation !== oldRotation) turns.set(i, (Number(rotation) / 90) % 4);
    }
    const store = this.registry.getStore();
    const pages = store.getState().core.documents[id]?.document?.pages;
    if (!turns.size || !pages) return false;
    // EmbedPDF no tiene una acción para girar una página: se cambia en su estado y se avisa.
    for (const [i, rotation] of turns) pages[i].rotation = rotation;
    store.dispatchToCore(refreshPages(id, [...turns.keys()]));
    this.registry.getPlugin('scroll').refreshDocumentLayout(id);
    // Como al volver a cargarlo, el historial de EmbedPDF empieza de nuevo: Ctrl+Z deshace
    // primero lo que hay en él y después las operaciones de página (ver Viewer.svelte).
    this.registry.getPlugin('history').provides().forDocument(id).purgeByMetadata(() => true);
    Object.assign(this, { sizes, keys, shownKeys: keys });
    return true;
  }

  /**
   * Vuelve a abrir el documento aunque no cambien las páginas (el OCR añadió texto). Las
   * anotaciones tienen que estar ya en Python (annotations.js `sync`): se reabre su versión.
   */
  reload() {
    if (this.registry) this.loading = this._load().catch((err) => this._fail(err));
  }

  /**
   * Termina la edición en curso en la página (texto libre de EmbedPDF): lo escrito se guarda
   * al perder el foco. EmbedPDF solo deja de editar con un clic en el fondo de la página (y
   * entonces quita también la selección): se le da ese clic. Si no, el cuadro seguía
   * admitiendo texto sin guardarlo.
   */
  finishEditing() {
    const editor = this.el.querySelector(`${ANNOTATION_LAYER} [contenteditable="true"]`);
    // La capa para el clic (mientras edita en esa página): no llega a las demás herramientas.
    editor?.closest('.pdf-page__pointer')?.dispatchEvent(new PointerEvent('pointerdown', { button: 0, isPrimary: true }));
    if (this.el.contains(document.activeElement)) document.activeElement.blur();
  }

  /**
   * `hook(index, documentId)` se llama al montar EmbedPDF cada página del documento a la vista;
   * lo que devuelva se llama al desmontarla.
   */
  onPageMount(hook) {
    this.mountHooks.push(hook);
  }

  _setSlots(sizes, keys) {
    this.sizes = sizes;
    this.keys = keys;
    this.slots = sizes.map(() => h('div', { class: 'pdf-page__layers' }));
  }

  destroy() {
    this.closed = true;
    for (const off of this.unsubscribe ?? []) off();
    if (this.pages) unmount(this.pages);
    // El registro es de toda la app: se cierra el documento de este visor (uno que aún se
    // esté cargando lo cierra _load al terminar). Se aplaza: destroy() corre mientras Svelte
    // desmonta la pestaña y cerrar ahora cambia el estado de EmbedPDF en mitad de ese cambio
    // (la pestaña siguiente no llegaba a mostrarse).
    const { registry: embed, shown } = this;
    if (shown) setTimeout(() => embed.getPlugin('document-manager').provides().closeDocument(shown));
  }

  get paged() {
    return this.mode !== MODES.CONTINUOUS;
  }

  get pageCount() {
    return this.sizes.length;
  }

  /** Miniaturas { página: url blob: } de la versión actual (liberarlas con `release`). */
  async thumbnails(pages) {
    await this.loading;
    const id = this.shown;
    if (!id || !sameKeys(this.shownKeys, this.keys)) return {};
    const render = this.registry.getPlugin('render').provides().forDocument(id);
    const result = {};
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

  /**
   * Páginas `pages` como imágenes para imprimir: `{ página: url blob: }` (liberarlas con
   * `release`), a `dpi` y con las anotaciones, dibujadas por PDFium como en el lienzo. `gray`:
   * en escala de grises (se pasa por un canvas: así sale igual en cualquier impresora).
   */
  async pageImages(pages, dpi, gray = false) {
    await this.loading;
    const id = this.shown;
    if (!id) return {};
    const render = this.registry.getPlugin('render').provides().forDocument(id);
    const result = {};
    for (const index of pages) {
      const { rotation } = this.pageInfo(index);
      const options = { scaleFactor: dpi / 72, rotation, dpr: 1, imageType: 'image/jpeg', imageQuality: PRINT_QUALITY, withAnnotations: true };
      let blob = await render.renderPage({ pageIndex: index, options }).toPromise();
      if (gray) blob = await grayscale(blob);
      result[index] = URL.createObjectURL(blob);
    }
    return result;
  }

  /** Página `index` del documento a la vista según EmbedPDF: `{ size }` sin girar y `rotation` (cuartos de vuelta). */
  pageInfo(index) {
    const page = this.registry?.getStore().getState().core.documents[this.shown]?.document?.pages[index];
    return page ?? { size: { width: this.sizes[index][0], height: this.sizes[index][1] }, rotation: 0 };
  }

  /** Rectángulo de EmbedPDF (página sin girar) → `[x0, y0, x1, y1]` en puntos de la página tal como se ve. */
  toView(index, rect) {
    const { size, rotation } = this.pageInfo(index);
    const r = transformRect(size, rect, rotation, 1);
    return [r.origin.x, r.origin.y, r.origin.x + r.size.width, r.origin.y + r.size.height];
  }

  /** Lo contrario de `toView`: `[x0, y0, x1, y1]` de la página tal como se ve → rectángulo de EmbedPDF. */
  toPage(index, [x0, y0, x1, y1]) {
    const { size, rotation } = this.pageInfo(index);
    const shown = rotation % 2 ? { width: size.height, height: size.width } : size;
    return transformRect(shown, { origin: { x: x0, y: y0 }, size: { width: x1 - x0, height: y1 - y0 } }, (4 - rotation) % 4, 1);
  }

  // ── Zoom ───────────────────────────────────────────────────────────────
  zoomIn() {
    this.setZoom(this.zoom * ZOOM_STEP);
  }

  zoomOut() {
    this.setZoom(this.zoom / ZOOM_STEP);
  }

  /** Cambia el zoom manteniendo fijo el punto bajo `anchor` (coordenadas de la ventana). */
  setZoom(factor, anchor = null) {
    const zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, factor));
    const box = this.el.getBoundingClientRect();
    this._requestZoom(zoom * UNIT, anchor ? { vx: anchor.x - box.left, vy: anchor.y - box.top } : undefined);
  }

  /** Ajustes que se mantienen al cambiar el tamaño de la ventana (EmbedPDF los recalcula). */
  fitWidth() {
    this._requestZoom(ZoomMode.FitWidth);
    this.scrollToPage(this.current);
  }

  fitPage() {
    this._requestZoom(ZoomMode.FitPage);
    this.scrollToPage(this.current);
  }

  _requestZoom(level, center) {
    this.level = level;
    if (this.ready) this._zoomScope().requestZoom(level, center);
    else if (typeof level === 'number') this._zoomChanged(level);
  }

  _zoomScope() {
    return this.registry.getPlugin('zoom').provides().forDocument(this.shown);
  }

  _zoomChanged(scale) {
    this.zoom = scale / UNIT;
    this.events.onZoom?.(this.zoom);
  }

  // ── Modos de vista y navegación ────────────────────────────────────────
  setMode(mode) {
    if (mode === this.mode) return;
    const anchor = this.current;
    this.mode = mode;
    if (this.shown) this._applyMode(this.shown);
    this.scrollToPage(anchor);
    this.events.onMode?.(mode);
  }

  _applyMode(id) {
    const { strategy, spread } = LAYOUTS[this.mode];
    this.registry.getPlugin('spread').provides().forDocument(id).setSpreadMode(spread);
    this.registry.getPlugin('scroll').provides().forDocument(id).setScrollStrategy(strategy);
  }

  step() {
    return pageStep(this.mode);
  }

  /** Lleva la página `index` a la vista (centrada, o su borde superior si no cabe). */
  scrollToPage(index, atBottom = false) {
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

  setNight(enabled) {
    this.el.classList.toggle('is-night', enabled);
  }

  setTool(tool) {
    this.tool = tool;
    this.el.dataset.tool = tool;
    if (this.shown) this._applyTool(this.shown);
  }

  _applyTool(id) {
    // Activar una herramienta de anotación cambia el modo del gestor de interacción (y quitarla
    // vuelve al predeterminado, el de texto).
    const annotationTool = ANNOTATION_TOOL[this.tool];
    const annotation = this.registry.getPlugin('annotation').provides().forDocument(id);
    if (annotationTool) {
      this.events.onTool?.(this.tool, id);
      annotation.setActiveTool(annotationTool);
      return;
    }
    if (annotation.getActiveTool()) annotation.setActiveTool(null);
    const mode = TEXT_TOOLS.has(this.tool) ? TEXT_MODE : OTHER_MODE;
    const interaction = this.registry.getPlugin('interaction-manager').provides().forDocument(id);
    if (interaction.getActiveMode() !== mode) interaction.activate(mode);
  }

  /** Centra en la vista el rectángulo `[x0, y0, x1, y1]` (puntos) de la página `index`. */
  scrollToRect(index, [x0, y0, x1, y1]) {
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
  _live() {
    return this.ready && sameKeys(this.shownKeys, this.keys);
  }

  /** En modo paginado, pasa a la fila (página o par) de `index`. */
  _showRow(index) {
    if (!this.paged) return;
    const { virtualItems } = this._scroll().getLayout();
    const row = virtualItems.find((item) => item.pageNumbers.includes(index + 1));
    if (!row) return;
    this.registry.getPlugin('scroll').showRow(this.shown, row.index);
    flushSync(); // que el Scroller ya mida lo que la fila nueva
  }

  _scroll() {
    return this.registry.getPlugin('scroll').provides().forDocument(this.shown);
  }

  /** EmbedPDF aplica los desplazamientos en el siguiente fotograma: así no se pisan con los suyos. */
  _scrollTo(x, y) {
    this.registry.getPlugin('viewport').provides().forDocument(this.shown).scrollTo({ x, y, behavior: 'instant' });
  }

  // ── Coordenadas y marcas ───────────────────────────────────────────────
  /** Página bajo (o más cerca de) un punto de la ventana y ese punto en puntos PDF. */
  pageAt(clientX, clientY) {
    let best = null;
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
  pointOn(index, clientX, clientY) {
    const box = this.pageRect(index);
    const [pw, ph] = this.sizes[index];
    return [((clientX - box.left) / box.width) * pw, ((clientY - box.top) / box.height) * ph];
  }

  /** Centro de la vista: la página que se ve ahí y ese punto (para insertar sellos). */
  viewCenter() {
    const box = this.el.getBoundingClientRect();
    return this.pageAt(box.left + this.el.clientWidth / 2, box.top + this.el.clientHeight / 2);
  }

  /** Capa de marcas de la página `index` (se crea al pedirla; se pierde con `setPages`). */
  marks(index) {
    const slot = this.slots[index];
    return slot.querySelector(':scope > .pdf-page__marks') ?? slot.appendChild(h('div', { class: 'pdf-page__marks' }));
  }

  /** Añade a la página `index` un rectángulo `[x0, y0, x1, y1]` en puntos con la clase `className`. */
  addMark(index, [x0, y0, x1, y1], className) {
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
  queryAll(selector) {
    return this.slots.flatMap((slot) => [...slot.querySelectorAll(selector)]);
  }

  /** Rectángulo de la página `index` en la ventana, esté montada o no. */
  pageRect(index) {
    const slot = this.slots[index];
    if (slot.isConnected || !this.ready) return slot.getBoundingClientRect();
    const r = this._viewRect(index);
    const box = this.el.getBoundingClientRect();
    const left = box.left + this.el.clientLeft + r.x - this.el.scrollLeft;
    const top = box.top + this.el.clientTop + r.y - this.el.scrollTop;
    return { left, top, width: r.w, height: r.h, right: left + r.w, bottom: top + r.h };
  }

  /** Rectángulo de la página `index` en píxeles del contenedor con scroll (según EmbedPDF). */
  _viewRect(index) {
    const { virtualItems, totalContentSize } = this._scroll().getLayout();
    const item = virtualItems.find((it) => it.pageNumbers.includes(index + 1));
    const page = item.pageLayouts.find((p) => p.pageIndex === index);
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

  _setCurrent(index, force = false) {
    if (index === this.current && !force) return;
    this.current = index;
    this.events.onPage?.(index);
  }

  // ── EmbedPDF ───────────────────────────────────────────────────────────
  async _start() {
    const embed = await registry();
    if (this.closed) return;
    this._connect(embed);
    this.pages = mount(PdfPages, {
      target: this.el,
      props: { element: this.el, overlay: (index) => (page) => this._attach(index, page) },
    });
    await this._load();
  }

  /** Avisos del registro (compartido por todos los visores): solo los de nuestro documento. */
  _connect(embed) {
    this.registry = embed;
    const scroll = embed.getPlugin('scroll').provides();
    const zoom = embed.getPlugin('zoom').provides();
    const viewport = embed.getPlugin('viewport').provides();
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
  async _load() {
    const seq = ++this.seq;
    const { url, keys } = await call('viewer.document_url', this.docId);
    const response = await fetch(url);
    if (!response.ok) throw new Error(`No se pudo descargar el documento (${response.status})`);
    const buffer = await response.arrayBuffer();
    if (this.closed || seq !== this.seq) return; // llegó otra versión más nueva
    const docs = this.registry.getPlugin('document-manager').provides();
    const { documentId, task } = await docs.openDocumentBuffer({
      buffer, name: `documento-${this.docId}.pdf`, documentId: `viewer-${this.docId}-${seq}`, autoActivate: false,
    }).toPromise();
    await task.toPromise();
    if (this.closed || seq !== this.seq) {
      docs.closeDocument(documentId);
      return;
    }
    if (this._live()) this.target = { index: this.current, atBottom: false };
    const previous = this.shown;
    this.finishEditing(); // mientras el documento anterior sigue abierto
    Object.assign(this, { shown: documentId, shownKeys: keys, ready: false });
    this._applyMode(documentId);
    this._applyTool(documentId);
    this.pages.show(documentId);
    flushSync(); // la vista suelta el documento anterior antes de cerrarlo
    if (previous) docs.closeDocument(previous);
    this.events.onDocument?.(documentId);
  }

  /** Engancha la capa de la página `index` a su página montada por EmbedPDF. */
  _attach(index, page) {
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

  _fail(err) {
    if (this.closed) return;
    console.error('No se pudo mostrar el documento con EmbedPDF', err);
    this.el.replaceChildren(h('p', { class: 'pdf-canvas__error' }, 'No se pudo mostrar el documento.'));
  }

  // ── Ratón: rueda (zoom con Ctrl, pasar página en modo paginado), clics y arrastre ──
  // El pellizco es del zoom de EmbedPDF (ZoomGestureWrapper).
  _onWheel(ev) {
    if (ev.ctrlKey) {
      ev.preventDefault();
      // Un paso de la rueda del ratón (100) es un paso de zoom; el trackpad da pasos más finos.
      if (ev.deltaY) this.setZoom(this.zoom * ZOOM_STEP ** (-ev.deltaY / WHEEL_NOTCH), { x: ev.clientX, y: ev.clientY });
      return;
    }
    if (this.paged && ev.deltaY && this._wheelFlip(ev.deltaY > 0)) ev.preventDefault();
  }

  /** Como en Adobe: primero se desplaza dentro de la página y solo en el borde pasa de página. */
  _wheelFlip(down) {
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
  _enablePanning() {
    let start = null;
    this.el.addEventListener('pointerdown', (ev) => {
      const box = this.el.getBoundingClientRect();
      const onScrollbar = ev.clientX - box.left >= this.el.clientWidth || ev.clientY - box.top >= this.el.clientHeight;
      // Sobre una anotación, el arrastre es suyo (moverla).
      if (ev.button !== 0 || onScrollbar || this.tool !== TOOLS.HAND || ev.target.closest?.(ANNOTATION)) return;
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

/** `blob` (imagen) en escala de grises, como JPEG. */
async function grayscale(blob) {
  const bitmap = await createImageBitmap(blob);
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const context = canvas.getContext('2d');
  context.filter = 'grayscale(1)';
  context.drawImage(bitmap, 0, 0);
  bitmap.close();
  return canvas.convertToBlob({ type: 'image/jpeg', quality: PRINT_QUALITY });
}
