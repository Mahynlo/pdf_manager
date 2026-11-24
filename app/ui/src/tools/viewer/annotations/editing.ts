// Barra de propiedades y teclado de las anotaciones seleccionadas (equivale a
// property_bar.py y annotation_editing.py en Qt). Seleccionar (Ctrl+clic añade o quita),
// mover, redimensionar, girar y editar el texto libre en la página (doble clic) lo hace la
// capa de anotaciones de EmbedPDF. Aquí:
//   · la barra sobre la selección: color, grosor, relleno y tamaño de letra (solo los que tiene
//     lo seleccionado; style/StyleButtons.svelte), editar el texto (nota, insertar o reemplazar
//     texto), en figuras y trazos duplicar y crear sello, traer al frente, enviar al fondo, eliminar;
//   · el teclado: Supr, Esc, Ctrl+D y las flechas (con Mayús, de 10 en 10 puntos);
//   · doble clic en una nota o una marca de inserción: editar su texto (diálogo).
import { PdfAnnotationSubtype as T, type Position, type Rect } from '@embedpdf/models';
import { h } from '$lib/dom.ts';
import { ic } from '$lib/icons.ts';
import { closePopover, popoverIn } from '$lib/popover.svelte.ts';
import { askText, toast } from '$lib/ui.ts';
import { t, tip } from '$texts';
import type { PageCanvas } from '../canvas/canvas.ts';
import type { Annot, AnnotDraft, Annotations } from './annotations.ts';
import { stampFromAnnotations } from '../stamps/library.svelte.ts';
import { mountStyleButtons, type MountedStyleButtons } from '../style/mount.svelte.ts';
import { NO_FILL, type ToolStyle } from './styles.svelte.ts';

const TX = t.viewer.annotations;
const WIDTH_TYPES = new Set([T.SQUARE, T.CIRCLE, T.LINE, T.INK, T.POLYLINE, T.POLYGON]);
const DRAWINGS = WIDTH_TYPES; // figuras y trazos: con Duplicar y Crear sello en la barra
const FILL_TYPES = new Set([T.SQUARE, T.CIRCLE, T.POLYGON, T.FREETEXT]);
const MARKUP_TYPES = new Set([T.HIGHLIGHT, T.UNDERLINE, T.STRIKEOUT, T.SQUIGGLY, T.TEXT, T.CARET]);
const TEXT_TYPES = new Set([T.TEXT, T.CARET]); // su texto se edita en un diálogo
const COLORLESS = new Set([T.STAMP, T.REDACT]); // imágenes; censura: su color lo da el panel
const NO_COPY = new Set([T.STAMP, T.LINK, T.WIDGET, T.POPUP, T.REDACT]); // sus datos no están en el objeto; marcas: las pone el panel
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

/** Color que se ve de `item`: la letra en el texto libre; el trazo en lo demás. */
const colorOf = (item: Annot): string => (item.type === T.FREETEXT ? item.fontColor : item.strokeColor ?? item.color) ?? '#000000';
/** Relleno de `item` (en el texto libre, su fondo). */
const fillOf = (item: Annot): string => (item.type === T.FREETEXT ? item.backgroundColor : item.color) ?? NO_FILL;

export class AnnotationEditor {
  canvas: PageCanvas;
  annotations: Annotations;
  items: Annot[] = []; // seleccionadas (objetos de EmbedPDF)
  dragging = false;
  bar: HTMLDivElement;
  styleButtons!: MountedStyleButtons;
  styleGroup!: HTMLSpanElement;
  noteButton!: HTMLButtonElement;
  copyButton!: HTMLButtonElement;
  stampButton!: HTMLButtonElement;
  frontButton!: HTMLButtonElement;
  backButton!: HTMLButtonElement;
  actionsSep!: HTMLSpanElement;

  constructor(canvas: PageCanvas, annotations: Annotations) {
    this.canvas = canvas;
    this.annotations = annotations;
    this.bar = this._buildBar();
    this._enable();
  }

  /** La selección cambió (aviso de annotations.ts). */
  setSelection(items: Annot[]): void {
    // Otra selección: se cierra el panel de estilo que estuviera abierto (si es la misma, p. ej.
    // tras cambiarle el grosor, sigue abierto para afinar).
    const same = items.length === this.items.length && items.every((item, i) => item.id === this.items[i].id);
    if (!same && popoverIn(this.bar)) closePopover();
    this.items = items;
    this._configureBar();
    this.placeBar();
    requestAnimationFrame(() => this.placeBar()); // con los botones de estilo ya pintados (Svelte)
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

  /** Sello propio con lo seleccionado (pide el nombre; queda en «Propios» del panel de sellos). */
  makeStamp(): void {
    if (this.canvas.shown) void stampFromAnnotations(this.annotations, this.canvas.shown, this.items);
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

  /** Un cambio de los botones de estilo: a lo seleccionado que lo tenga. */
  _setStyle(patch: Partial<ToolStyle>): void {
    if (patch.color) this.setColor(patch.color);
    if (patch.fill) this._setFill(patch.fill);
    const { width, fontSize } = patch;
    if (width != null) this.annotations.update(this.items, (item) => (WIDTH_TYPES.has(item.type) ? { strokeWidth: width } : null));
    if (fontSize != null) this.annotations.update(this.items, (item) => (item.type === T.FREETEXT ? { fontSize } : null));
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
      if (popoverIn(this.bar)) closePopover();
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
    this.styleGroup = h('span', { class: 'prop-bar__style' });
    this.styleButtons = mountStyleButtons(this.styleGroup, (patch) => this._setStyle(patch));
    this.canvas.loading.then(() => this.canvas.unsubscribe.push(() => this.styleButtons.destroy()));
    this.noteButton = iconButton('pencil', B.editText, () => this.editNote(this.items[0]));
    this.copyButton = iconButton('copy', tip(B.duplicate), () => this.duplicate());
    this.stampButton = iconButton('stamp', B.stamp, () => this.makeStamp());
    this.frontButton = iconButton('arrow-up', B.front, () => this.order(true));
    this.backButton = iconButton('arrow-down', B.back, () => this.order(false));
    this.actionsSep = h('span', { class: 'sel-bar__sep', 'aria-hidden': 'true' });
    return h('div', { class: 'prop-bar', role: 'toolbar', 'aria-label': B.label, hidden: true, onpointerdown: stop },
      this.styleGroup, this.noteButton,
      this.actionsSep,
      this.copyButton, this.stampButton,
      this.frontButton, this.backButton,
      iconButton('trash', tip(B.remove), () => this.remove(), 'is-danger'),
      iconButton('x', B.close, () => this.clear()),
    );
  }

  /**
   * Muestra solo los controles que aplican a lo seleccionado (como configure_for_items). Con
   * varias anotaciones distintas, cada valor es el de la primera que lo tiene.
   */
  _configureBar(): void {
    const { items } = this;
    this.bar.hidden = !items.length || this.dragging;
    if (!items.length) return;
    const colored = items.filter((item) => !COLORLESS.has(item.type));
    const withWidth = items.find((item) => WIDTH_TYPES.has(item.type));
    const withFill = items.find((item) => FILL_TYPES.has(item.type));
    const text = items.find((item) => item.type === T.FREETEXT);
    const style: Partial<ToolStyle> = {};
    if (colored.length) style.color = colorOf(colored[0]);
    if (withWidth) style.width = withWidth.strokeWidth ?? 1;
    if (withFill) style.fill = fillOf(withFill);
    if (text) style.fontSize = text.fontSize ?? 12;
    const hasStyle = Object.keys(style).length > 0;
    const onlyText = colored.length > 0 && colored.every((item) => item.type === T.FREETEXT);
    this.styleButtons.set(hasStyle ? style : null, onlyText ? t.viewer.annotations.style.textColor : undefined);
    this.styleGroup.hidden = !hasStyle;
    this.noteButton.hidden = !(items.length === 1 && TEXT_TYPES.has(items[0].type));
    // Sin nada delante (p. ej. una imagen), sobra el separador de las acciones.
    this.actionsSep.hidden = !hasStyle && this.noteButton.hidden;
    this.frontButton.hidden = this.backButton.hidden = items.every((item) => item.type === T.STAMP);
    // Figuras y trazos (con texto o notas, también): duplicar y guardar como sello.
    this.copyButton.hidden = this.stampButton.hidden = !items.some((item) => DRAWINGS.has(item.type))
      || items.some((item) => NO_COPY.has(item.type));
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
