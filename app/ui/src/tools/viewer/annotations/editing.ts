// Barra de propiedades y teclado de las anotaciones seleccionadas (equivale a
// property_bar.py y annotation_editing.py en Qt). Seleccionar (Ctrl+clic añade o quita),
// mover, redimensionar, girar y editar el texto libre en la página (doble clic) lo hace la
// capa de anotaciones de EmbedPDF. Aquí:
//   · la barra sobre la selección: color, grosor, tamaño de letra, relleno, editar el texto
//     (nota, insertar o reemplazar texto), traer al frente, enviar al fondo, duplicar, eliminar;
//   · el teclado: Supr, Esc, Ctrl+D y las flechas (con Mayús, de 10 en 10 puntos);
//   · doble clic en una nota o una marca de inserción: editar su texto (diálogo).
import { PdfAnnotationSubtype as T, type Position, type Rect } from '@embedpdf/models';
import { h } from '$lib/dom.ts';
import { ic } from '$lib/icons.ts';
import { openMenu } from '$lib/menu.svelte.ts';
import { askText, toast } from '$lib/ui.ts';
import { t, tip } from '$texts';
import type { PageCanvas } from '../canvas/canvas.ts';
import type { Annot, AnnotDraft, Annotations } from './annotations.ts';
import { FONT_SIZES, PRESET_COLORS, STROKE_WIDTHS } from './palette.ts';

const TX = t.viewer.annotations;
const WIDTH_TYPES = new Set([T.SQUARE, T.CIRCLE, T.LINE, T.INK, T.POLYLINE, T.POLYGON]);
const FILL_TYPES = new Set([T.SQUARE, T.CIRCLE, T.POLYGON, T.FREETEXT]);
const MARKUP_TYPES = new Set([T.HIGHLIGHT, T.UNDERLINE, T.STRIKEOUT, T.SQUIGGLY, T.TEXT, T.CARET]);
const TEXT_TYPES = new Set([T.TEXT, T.CARET]); // su texto se edita en un diálogo
const COLORLESS = new Set([T.STAMP, T.REDACT]); // imágenes; censura: su color lo da el panel
const NO_COPY = new Set([T.STAMP, T.LINK, T.WIDGET, T.POPUP, T.REDACT]); // sus datos no están en el objeto; marcas: las pone el panel
const NONE = 'transparent'; // sin relleno, para EmbedPDF
const DUPLICATE_OFFSET = 7.5; // pt (15 en la escena de Qt)
const BAR_GAP = 12; // px entre la selección y la barra
const ROTATE_CLEARANCE = 56; // px sobre la selección que ocupa el tirador de giro de EmbedPDF
const NUDGE: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
const ANNOTATION = '#annotation-layer'; // capa de anotaciones de EmbedPDF (PdfPage.svelte)

type Patch = Record<string, unknown> | null;

/**
 * Cambio de color según el tipo: el texto libre cambia la letra (la llamada, también su
 * flecha); las marcas y notas, ambos colores; las imágenes no cambian.
 */
function colorPatch(item: Annot, color: string): Patch {
  if (COLORLESS.has(item.type)) return null;
  if (item.type === T.FREETEXT) return item.intent === 'FreeTextCallout' ? { fontColor: color, strokeColor: color } : { fontColor: color };
  if (MARKUP_TYPES.has(item.type)) return { strokeColor: color, color };
  return { strokeColor: color };
}

/** Copia de `object` desplazada (dx, dy) puntos en la página sin girar. */
function shifted(object: Annot, dx: number, dy: number): AnnotDraft {
  const point = (p: Position): Position => ({ x: p.x + dx, y: p.y + dy });
  const rect = (r: Rect): Rect => ({ origin: point(r.origin), size: r.size });
  const copy: AnnotDraft = { ...object, rect: rect(object.rect) };
  if (object.unrotatedRect) copy.unrotatedRect = rect(object.unrotatedRect);
  if (object.inkList) copy.inkList = object.inkList.map((stroke: { points: Position[] }) => ({ ...stroke, points: stroke.points.map(point) }));
  if (object.linePoints) copy.linePoints = { start: point(object.linePoints.start), end: point(object.linePoints.end) };
  if (object.segmentRects) copy.segmentRects = object.segmentRects.map(rect);
  if (object.vertices) copy.vertices = object.vertices.map(point);
  if (object.calloutLine) copy.calloutLine = object.calloutLine.map(point);
  return copy;
}

const nearest = (values: number[], value: number) => values.reduce((a, b) => (Math.abs(b - value) < Math.abs(a - value) ? b : a));

export class AnnotationEditor {
  canvas: PageCanvas;
  annotations: Annotations;
  items: Annot[] = []; // seleccionadas (objetos de EmbedPDF)
  dragging = false;
  bar: HTMLDivElement;
  widthSelect!: HTMLSelectElement;
  fontSelect!: HTMLSelectElement;
  fillButton!: HTMLButtonElement;
  noteButton!: HTMLButtonElement;
  copyButton!: HTMLButtonElement;
  frontButton!: HTMLButtonElement;
  backButton!: HTMLButtonElement;
  actionsSep!: HTMLSpanElement;
  colors!: HTMLSpanElement;

  constructor(canvas: PageCanvas, annotations: Annotations) {
    this.canvas = canvas;
    this.annotations = annotations;
    this.bar = this._buildBar();
    this._enable();
  }

  /** La selección cambió (aviso de annotations.ts). */
  setSelection(items: Annot[]): void {
    this.items = items;
    this._configureBar();
    this.placeBar();
    // Sin selección (la X de la barra, por ejemplo) tampoco se sigue escribiendo en un texto
    // libre. Después del cambio: un clic en el fondo ya lo habrá terminado.
    if (!items.length) requestAnimationFrame(() => !this.items.length && this.canvas.finishEditing());
  }

  /** Esc mientras se escribe un texto libre: termina y lo deja seleccionado. */
  stopTyping(): boolean {
    if (!this._typing()) return false;
    const { items } = this;
    this.canvas.finishEditing();
    this.annotations.select(items);
    return true;
  }

  clear(): void {
    this.annotations.clearSelection();
  }

  // ── Teclado (lo llama el visor si la pestaña está activa) ──────────────
  onKey(ev: KeyboardEvent): boolean {
    if (!this.items.length || ev.altKey) return false;
    const { key } = ev;
    if (key === 'Delete' || key === 'Backspace') {
      this.remove();
      return true;
    }
    if (key === 'Escape') {
      this.clear();
      return true;
    }
    if (ev.ctrlKey && key.toLowerCase() === 'd') {
      this.duplicate();
      return true;
    }
    const nudge = NUDGE[key];
    if (nudge && !ev.ctrlKey) {
      const step = ev.shiftKey ? 10 : 1;
      this.annotations.move(this.items, nudge[0] * step, nudge[1] * step);
      return true;
    }
    return false;
  }

  // ── Acciones de la barra ───────────────────────────────────────────────
  remove(): void {
    const { items } = this;
    this.clear();
    this.annotations.remove(items);
  }

  duplicate(): void {
    const copies = this.items.filter((item) => !NO_COPY.has(item.type))
      .map((item) => shifted(item, DUPLICATE_OFFSET, DUPLICATE_OFFSET));
    if (copies.length) this.annotations.select(this.annotations.create(copies));
  }

  /** Traer al frente o enviar al fondo (como el menú de las anotaciones en Qt). */
  async order(front: boolean): Promise<void> {
    const moved = await this.annotations.reorder(this.items, front);
    if (!moved) {
      toast(TX.bar.cantReorder, 'warning');
      return;
    }
    this.annotations.select(moved);
  }

  setColor(color: string): void {
    this.annotations.update(this.items, (item) => colorPatch(item, color));
  }

  _setFill(color: string): void {
    this.annotations.update(this.items, (item) => (FILL_TYPES.has(item.type) ? { color, backgroundColor: color } : null));
  }

  /** Texto de una nota o de una marca de insertar o reemplazar texto. */
  async editNote(item: Annot): Promise<void> {
    const [title, label] = item.type === T.CARET ? [TX.editTextTitle, TX.editTextLabel] : [TX.editNoteTitle, TX.noteLabel];
    const text = await askText(title, label, item.contents ?? '', { multiline: true });
    if (text != null && text.trim() !== (item.contents ?? '')) {
      this.annotations.update([item], () => ({ contents: text.trim() }));
    }
  }

  // ── Ratón ──────────────────────────────────────────────────────────────
  _enable(): void {
    const el: HTMLElement = this.canvas.el;
    const inLayer = (ev: Event) => Boolean((ev.target as Element | null)?.closest?.(ANNOTATION));
    // Mientras se arrastra una anotación la barra se esconde (se queda atrás).
    el.addEventListener('pointerdown', (ev) => {
      if (!inLayer(ev)) return;
      this.dragging = true;
      this.bar.hidden = true;
    }, { capture: true });
    // En captura en la ventana: EmbedPDF para el `pointerup` del arrastre.
    const release = () => {
      if (!this.dragging) return;
      this.dragging = false;
      requestAnimationFrame(() => this.setSelection(this.annotations.selected()));
    };
    window.addEventListener('pointerup', release, { capture: true });
    this.canvas.loading.then(() => this.canvas.unsubscribe.push(() => window.removeEventListener('pointerup', release, { capture: true })));
    el.addEventListener('dblclick', (ev) => {
      const [item, ...rest] = this.items;
      if (item && TEXT_TYPES.has(item.type) && !rest.length && inLayer(ev)) this.editNote(item);
    });
    el.addEventListener('scroll', () => this.placeBar(), { passive: true });
    // Al empezar y terminar de escribir un texto libre, la barra cambia de lado.
    el.addEventListener('focusin', () => this.placeBar());
    el.addEventListener('focusout', () => requestAnimationFrame(() => this.placeBar()));
  }

  // ── Barra de propiedades (AnnotationPropertyBar) ───────────────────────
  _buildBar(): HTMLDivElement {
    const B = TX.bar;
    const stop = (ev: Event) => ev.stopPropagation();
    const iconButton = (icon: string, title: string, onclick: () => void, extra = '') => h('button', {
      class: `btn btn--icon btn--sm ${extra}`, type: 'button', title, 'aria-label': title, onclick, onpointerdown: stop,
    }, ic(icon));
    const custom = h('input', { type: 'color', class: 'prop-bar__picker', tabindex: '-1', onchange: () => this.setColor(custom.value.toUpperCase()) });
    const fillPicker = h('input', { type: 'color', class: 'prop-bar__picker', tabindex: '-1', onchange: () => this._setFill(fillPicker.value.toUpperCase()) });
    this.widthSelect = h('select', {
      class: 'input input--sm prop-bar__select', title: B.width, onpointerdown: stop,
      onchange: () => this.annotations.update(this.items, (item) => (WIDTH_TYPES.has(item.type) ? { strokeWidth: Number(this.widthSelect.value) } : null)),
    }, STROKE_WIDTHS.map((w) => h('option', { value: String(w) }, B.points(w))));
    this.fontSelect = h('select', {
      class: 'input input--sm prop-bar__select', title: B.fontSize, onpointerdown: stop,
      onchange: () => this.annotations.update(this.items, (item) => (item.type === T.FREETEXT ? { fontSize: Number(this.fontSelect.value) } : null)),
    }, FONT_SIZES.map((s) => h('option', { value: String(s) }, B.points(s))));
    this.fillButton = iconButton('paint-bucket', B.fill, () => openMenu(this.fillButton, [
      { label: B.noFill, icon: 'x', onSelect: () => this._setFill(NONE) },
      'separator',
      ...PRESET_COLORS.map(([color, name]) => ({ label: name, icon: 'circle', onSelect: () => this._setFill(color) })),
      'separator',
      { label: B.custom, icon: 'palette', onSelect: () => fillPicker.click() },
    ]));
    this.noteButton = iconButton('pencil', B.editText, () => this.editNote(this.items[0]));
    this.copyButton = iconButton('copy', tip(B.duplicate), () => this.duplicate());
    this.frontButton = iconButton('arrow-up', B.front, () => this.order(true));
    this.backButton = iconButton('arrow-down', B.back, () => this.order(false));
    this.actionsSep = h('span', { class: 'sel-bar__sep', 'aria-hidden': 'true' });
    this.colors = h('span', { class: 'prop-bar__colors' },
      PRESET_COLORS.map(([color, name]) => h('button', {
        class: 'tb-swatch', type: 'button', title: name, 'aria-label': name, style: { '--swatch': color },
        onclick: () => this.setColor(color),
      })),
      iconButton('palette', B.customColor, () => custom.click()), custom,
      h('span', { class: 'sel-bar__sep', 'aria-hidden': 'true' }));
    return h('div', { class: 'prop-bar', role: 'toolbar', hidden: true, onpointerdown: stop },
      this.colors,
      this.widthSelect, this.fontSelect, this.fillButton, fillPicker, this.noteButton,
      this.actionsSep,
      this.frontButton, this.backButton,
      this.copyButton,
      iconButton('trash', tip(B.remove), () => this.remove(), 'is-danger'),
      iconButton('x', B.close, () => this.clear()),
    );
  }

  /** Muestra solo los controles que aplican a lo seleccionado (como configure_for_items). */
  _configureBar(): void {
    const { items } = this;
    this.bar.hidden = !items.length || this.dragging;
    if (!items.length) return;
    const withWidth = items.find((item) => WIDTH_TYPES.has(item.type));
    const text = items.find((item) => item.type === T.FREETEXT);
    this.widthSelect.hidden = !withWidth;
    if (withWidth) this.widthSelect.value = String(nearest(STROKE_WIDTHS, withWidth.strokeWidth ?? 1));
    this.fontSelect.hidden = !text;
    if (text) this.fontSelect.value = String(nearest(FONT_SIZES, text.fontSize ?? 12));
    this.fillButton.hidden = !items.some((item) => FILL_TYPES.has(item.type));
    this.noteButton.hidden = !(items.length === 1 && TEXT_TYPES.has(items[0].type));
    this.colors.hidden = items.every((item) => COLORLESS.has(item.type));
    // Sin nada delante (p. ej. una imagen), sobra el separador de las acciones.
    this.actionsSep.hidden = this.colors.hidden
      && [this.widthSelect, this.fontSelect, this.fillButton, this.noteButton].every((el) => el.hidden);
    this.copyButton.hidden = items.every((item) => NO_COPY.has(item.type));
    this.frontButton.hidden = this.backButton.hidden = items.every((item) => item.type === T.STAMP);
  }

  /** ¿Se está escribiendo en un texto libre de la página? */
  _typing(): boolean {
    const active = document.activeElement as HTMLElement | null;
    return Boolean(active?.isContentEditable && this.canvas.el.contains(active));
  }

  /** Rectángulos de la selección en la ventana (de las páginas montadas). */
  _clientRects(): { left: number; right: number; top: number; bottom: number }[] {
    return this.items.filter((item) => this.canvas.mounted.has(item.pageIndex)).map((item) => {
      const [x0, y0, x1, y1]: number[] = this.canvas.toView(item.pageIndex, item.rect);
      const page = this.canvas.pageRect(item.pageIndex);
      const [pw, ph]: [number, number] = this.canvas.sizes[item.pageIndex];
      const sx = page.width / pw;
      const sy = page.height / ph;
      return { left: page.left + x0 * sx, right: page.left + x1 * sx, top: page.top + y0 * sy, bottom: page.top + y1 * sy };
    });
  }

  /**
   * Debajo de la selección, centrada; si no cabe, encima. Encima de la selección EmbedPDF
   * pone el tirador de giro: la barra no lo tapa (deja ROTATE_CLEARANCE). Mientras se escribe
   * un texto libre va encima: lo escrito puede sobresalir por debajo de la caja.
   */
  placeBar(): void {
    if (this.bar.hidden) return;
    // Si la selección quedó lejos (páginas no montadas), la barra no se ve.
    const marks = this._clientRects();
    this.bar.style.visibility = marks.length ? '' : 'hidden';
    const stage = (this.bar.offsetParent as HTMLElement | null)?.getBoundingClientRect();
    if (!marks.length || !stage) return;
    const view = this.canvas.el.getBoundingClientRect();
    const { width, height } = this.bar.getBoundingClientRect();
    const left = Math.min(...marks.map((r) => r.left));
    const right = Math.max(...marks.map((r) => r.right));
    const top = Math.min(...marks.map((r) => r.top));
    const bottom = Math.max(...marks.map((r) => r.bottom));
    const above = Math.max(view.top + 10, top - ROTATE_CLEARANCE - height);
    let y = bottom + BAR_GAP;
    if (this._typing() || y + height > view.bottom - 10) y = above;
    const x = Math.max(view.left + 10, Math.min((left + right) / 2 - width / 2, view.right - width - 24));
    this.bar.style.left = `${x - stage.left}px`;
    this.bar.style.top = `${y - stage.top}px`;
  }
}
