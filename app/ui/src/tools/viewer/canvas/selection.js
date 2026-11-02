// Selección de texto en el lienzo (equivale a canvas/text_selection.py y
// selection_bar.py en Qt), con el complemento Selection de EmbedPDF (paso 3 de
// docs/web/embedpdf.md): arrastrar selecciona, también entre páginas; doble clic, una
// palabra; triple clic, una línea; Ctrl+A, el texto de la página. Con las herramientas de
// texto (resaltar, subrayar, tachar, ondulado, insertar y reemplazar), la selección se
// convierte en anotación.
//
// EmbedPDF calcula la selección con el texto que PDFium lee del documento (el de OCR va
// en él como texto invisible, ver viewer.document_url). Aquí se dibuja con nuestras
// marcas (`.sel-rect`) y se muestra la barra flotante con sus acciones. Las coordenadas
// de EmbedPDF son de la página sin girar; las nuestras, de la página tal como se ve, en
// puntos (como las de Python): las pasa `canvas.toView`.
import { call } from '$lib/api.js';
import { h } from '$lib/dom.js';
import { ic } from '$lib/icons.js';
import { setStatus, toast } from '$lib/ui.js';
import { MARKUP_TOOLS, TOOLS } from './canvas.js';
import { TEXT_MODE } from './embed.js';

const SEPARATOR_BEFORE_PAGE = '\n';
const BAR_GAP = 8; // px entre la selección y la barra flotante
const WHOLE_PAGE = Number.MAX_SAFE_INTEGER; // índice de carácter que EmbedPDF recorta al último

export class TextSelection {
  /**
   * @param {import('./canvas.js').PageCanvas} canvas
   * @param {{ searchDocument: (text) => void, markup: (kind, pages) => void, redact: (text, pages) => void,
   *   explain: (text) => void }} actions
   *   acciones de la barra flotante; `markup(kind, partes)` crea la anotación (partes de
   *   `getFormattedSelection` de EmbedPDF: `{ pageIndex, rect, segmentRects }` en la página sin
   *   girar), `redact(texto, partes)` la marca para censurarla y
   *   `explain(texto)`, al asistente IA.
   */
  constructor(canvas, actions) {
    this.canvas = canvas;
    this.actions = actions;
    this.text = '';
    this.pages = []; // [{ page, rects }] seleccionado, en puntos de la página tal como se ve
    this.request = 0; // para descartar textos que llegan tarde
    this.bar = this._buildBar();
    canvas.onPageMount((index, documentId) => this._register(index, documentId));
    canvas.loading.then(() => this._connect());
    canvas.el.addEventListener('scroll', () => this.placeBar(), { passive: true });
  }

  get hasSelection() {
    return Boolean(this.text);
  }

  /** Las páginas cambiaron (rotar, mover…): la selección ya no vale. */
  reset() {
    this.clear();
  }

  clear() {
    for (const mark of this.canvas.queryAll('.sel-rect')) mark.remove();
    this.pages = [];
    this.text = '';
    this.request++;
    this.bar.hidden = true;
    const scope = this._scope();
    if (scope?.getState().selection) scope.clear();
  }

  /** Ctrl+A: todo el texto de la página actual. */
  async selectPage(index = this.canvas.current) {
    const scope = this._scope();
    if (!scope) return;
    try {
      await scope.setSelection({ start: { page: index, index: 0 }, end: { page: index, index: WHOLE_PAGE } }).toPromise();
    } catch {
      return; // página sin texto
    }
    this._finish();
  }

  /** ¿Hay texto bajo el puntero? (cursor de texto). EmbedPDF lo sabe al mover el ratón. */
  overText() {
    return this._interaction()?.getCurrentCursor() === 'text';
  }

  copy() {
    if (!this.text) return false;
    navigator.clipboard.writeText(this.text)
      .then(() => setStatus('Texto copiado al portapapeles'))
      .catch((err) => toast(`No se pudo copiar: ${err.message}`, 'danger'));
    this.clear();
    return true;
  }

  // ── EmbedPDF ───────────────────────────────────────────────────────────
  _plugin() {
    return this.canvas.registry?.getPlugin('selection');
  }

  _scope() {
    const { shown } = this.canvas;
    return shown ? this._plugin()?.provides().forDocument(shown) : null;
  }

  _interaction() {
    const { shown } = this.canvas;
    return shown ? this.canvas.registry.getPlugin('interaction-manager').provides().forDocument(shown) : null;
  }

  /** Avisos de la selección (el registro es de toda la app: solo los de nuestro documento). */
  _connect() {
    const selection = this._plugin()?.provides();
    if (!selection || this.canvas.closed) return;
    const ours = (documentId) => documentId === this.canvas.shown;
    this.canvas.unsubscribe.push(
      selection.onSelectionChange(({ documentId, selection: range }) => {
        if (!ours(documentId)) return;
        if (range) this._drawAll();
        else if (this.text || this.pages.length) this.clear();
      }),
      selection.onBeginSelection(({ documentId }) => {
        if (!ours(documentId)) return;
        this.text = '';
        this.bar.hidden = true;
      }),
      selection.onEndSelection(({ documentId }) => {
        if (ours(documentId)) this._finish();
      }),
    );
    // EmbedPDF termina el arrastre con el `pointerup` de la página donde empezó: si se suelta
    // en otra página, entre páginas o fuera del lienzo, no lo termina. Se termina aquí.
    const release = () => {
      const { shown } = this.canvas;
      if (shown && this._scope()?.getState().selecting) this._plugin().endSelection(shown, TEXT_MODE);
    };
    document.addEventListener('pointerup', release);
    this.canvas.unsubscribe.push(() => document.removeEventListener('pointerup', release));
  }

  /** Al montarse una página: la selección escucha su ratón y avisa de sus rectángulos. */
  _register(index, documentId) {
    const plugin = this._plugin();
    if (!plugin || !documentId) return undefined;
    return plugin.registerSelectionOnPage({
      documentId,
      pageIndex: index,
      onRectsChange: ({ rects }) => {
        if (documentId === this.canvas.shown) this._draw(index, rects);
      },
    });
  }

  _draw(index, rects) {
    if (!this.canvas.slots[index]) return;
    for (const mark of this.canvas.marks(index).querySelectorAll('.sel-rect')) mark.remove();
    for (const rect of rects) this.canvas.addMark(index, this.canvas.toView(index, rect), 'sel-rect');
  }

  _drawAll() {
    const all = this._scope()?.getHighlightRects() ?? {};
    for (const mark of this.canvas.queryAll('.sel-rect')) mark.remove();
    for (const [index, rects] of Object.entries(all)) this._draw(Number(index), rects);
  }

  /** Fin de la selección: texto, barra flotante y aviso en la barra de estado. */
  async _finish() {
    const scope = this._scope();
    // Con «Marcar» (censura) la selección es del complemento de censura: la convierte en marca.
    if (!scope || this.canvas.tool === TOOLS.REDACT) return;
    const request = ++this.request;
    this.pages = Object.entries(scope.getHighlightRects())
      .filter(([, rects]) => rects.length)
      .map(([index, rects]) => ({ page: Number(index), rects: rects.map((r) => this.canvas.toView(Number(index), r)) }));
    let parts = [];
    try {
      parts = await scope.getSelectedText().toPromise();
    } catch (err) {
      console.warn('No se pudo leer el texto seleccionado', err);
    }
    if (request !== this.request) return; // otra selección más nueva
    this.text = parts.map((part) => part.replace(/\r\n?/g, '\n')).join(SEPARATOR_BEFORE_PAGE);
    if (!this.text.trim()) {
      this.clear();
      return;
    }
    if (MARKUP_TOOLS[this.canvas.tool]) {
      this.markup(MARKUP_TOOLS[this.canvas.tool]);
      return;
    }
    const page = this.pages.at(-1).page;
    setStatus(`${this.text.length} caracteres seleccionados en la página ${page + 1}`);
    this.bar.hidden = false;
    this.placeBar();
  }

  /** Anota lo seleccionado (`kind`: highlight | underline | strikeout | squiggly | insert | replace). */
  markup(kind) {
    const parts = this._scope()?.getFormattedSelection() ?? [];
    this.clear();
    if (parts.length) this.actions.markup(kind, parts);
  }

  /** «Enviar selección a censura»: lo seleccionado queda marcado para censurarlo. */
  redact() {
    const { text } = this;
    const parts = this._scope()?.getFormattedSelection() ?? [];
    this.clear();
    if (parts.length) this.actions.redact(text, parts);
  }

  // ── Barra flotante (como FloatingSelectionBar) ─────────────────────────
  _buildBar() {
    const button = (icon, title, onclick, label) => h('button', {
      class: `btn btn--sm sel-bar__btn ${label ? 'btn--ghost' : 'btn--icon'}`, type: 'button', title, 'aria-label': title,
      onpointerdown: (ev) => ev.stopPropagation(), onclick,
    }, ic(icon, 16), label ?? null);
    const take = (fn) => () => {
      const { text } = this;
      this.bar.hidden = true;
      if (text) fn(text);
    };
    return h('div', { class: 'sel-bar', role: 'toolbar', hidden: true },
      button('copy', 'Copiar texto seleccionado (Ctrl+C)', () => this.copy(), 'Copiar'),
      button('highlighter', 'Resaltar selección', () => this.markup('highlight')),
      button('underline', 'Subrayar selección', () => this.markup('underline')),
      button('strikethrough', 'Tachar selección', () => this.markup('strikeout')),
      button('squiggly', 'Subrayado ondulado', () => this.markup('squiggly')),
      button('eraser', 'Enviar selección a censura', () => this.redact()),
      h('span', { class: 'sel-bar__sep', 'aria-hidden': 'true' }),
      button('search', 'Buscar en el documento', take((text) => this.actions.searchDocument(text))),
      button('globe', 'Buscar en Google', take((text) =>
        call('app.open_url', `https://www.google.com/search?q=${encodeURIComponent(text.slice(0, 200).trim())}`))),
      button('sparkles', 'Explicar con Agente IA', take((text) => this.actions.explain(text))),
      button('x', 'Descartar selección', () => this.clear()),
    );
  }

  /** Debajo de la selección o, si no cabe, encima (como _update_floating_bar_position). */
  placeBar() {
    if (this.bar.hidden) return;
    // Solo las marcas de páginas montadas: si la selección quedó lejos, la barra no se ve.
    const marks = this.canvas.queryAll('.sel-rect').filter((m) => m.isConnected).map((m) => m.getBoundingClientRect());
    this.bar.style.visibility = marks.length ? '' : 'hidden';
    if (!marks.length) return;
    const stage = this.bar.offsetParent?.getBoundingClientRect();
    if (!stage) return;
    const left = Math.min(...marks.map((r) => r.left));
    const top = Math.min(...marks.map((r) => r.top));
    const bottom = Math.max(...marks.map((r) => r.bottom));
    const { width, height } = this.bar.getBoundingClientRect();
    const view = this.canvas.el.getBoundingClientRect();
    let y = bottom - stage.top + BAR_GAP;
    if (y + height > view.bottom - stage.top - 10) y = Math.max(10, top - stage.top - height - BAR_GAP);
    const x = Math.max(10, Math.min(left - stage.left, view.right - stage.left - width - 24));
    this.bar.style.left = `${x}px`;
    this.bar.style.top = `${y}px`;
  }
}
