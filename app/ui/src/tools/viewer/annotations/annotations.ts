// Anotaciones del visor (equivale a canvas/items y annotation_io.py en Qt) con el
// complemento Annotation de EmbedPDF (paso 4 de docs/web/embedpdf.md).
//
// EmbedPDF las dibuja (su capa en PdfPage.svelte), las selecciona, las mueve y redimensiona,
// edita el texto libre en la página y crea las nuevas con sus herramientas (rectángulo,
// círculo, línea, flecha, polilínea, polígono, pluma, marcador, texto libre, llamada, nota e
// imagen: las activa canvas.ts). Su historial da deshacer y rehacer. Aquí está lo nuestro:
//   · el estilo de cada visor (colores y grosores), que se da a la herramienta al activarla;
//   · las anotaciones de la selección de texto: resaltar, subrayar, tachar, ondulado, insertar
//     y reemplazar texto (estas dos piden el texto); y los sellos y leyendas;
//   · tras dibujar una forma, el texto, la llamada, la nota o la imagen, volver al puntero con
//     ella seleccionada (como Qt); la nota pide antes su texto;
//   · juntar en un solo paso de deshacer lo que se crea a la vez (`batch`: p. ej. las marcas de
//     censura de un término, ver redaction.ts);
//   · traer al frente y enviar al fondo (`reorder`), que EmbedPDF no sabe hacer;
//   · avisar de cada cambio (`onChanged`): hay cambios sin guardar y Python aún no los tiene (la
//     copia que se le pasa es la de document/copy.ts).
//
// Las coordenadas de EmbedPDF son de la página sin girar (canvas.toView / toPage las pasan
// a las de la página tal como se ve).
import {
  PdfAnnotationReplyType, PdfAnnotationSubtype, PdfStandardFont, PdfTextAlignment, PdfVerticalAlignment, uuidV4,
  type PdfAnnotationObject, type Rect,
} from '@embedpdf/models';
import type { PluginRegistry } from '@embedpdf/core';
import {
  applyInsertUpright, type AnnotationEvent, type AnnotationPlugin, type AnnotationScope,
} from '@embedpdf/plugin-annotation';
import type { Command, HistoryPlugin, HistoryScope } from '@embedpdf/plugin-history';
import { askText } from '$lib/ui.ts';
import { t } from '$texts';
import { ANNOTATION_TOOL, TOOLS, type PageCanvas } from '../canvas/canvas.ts';
import { KINDS, MANUAL_LABEL, type SelectionPart } from '../redact/redaction.ts';
import { TEXT_STAMP, textStampSize, type TextStamp } from '../stamps/stamp-pdf.ts';
import { DEFAULT_STYLE, type AnnotationStyle } from './palette.ts';

/**
 * Anotación de EmbedPDF. Es una unión de tipos (rectángulo, texto libre, nota…) y el código lee
 * campos que solo tienen algunos (`fontSize`, `inReplyToId`, `intent`…): se da acceso a todos.
 */
export type Annot = PdfAnnotationObject & Record<string, any>;

/** Anotación a crear: lo que lleva el objeto, sin `id` (lo pone `create`). */
export type AnnotDraft = { type: PdfAnnotationSubtype; pageIndex: number; rect: Rect } & Record<string, any>;

/** Estado del historial de EmbedPDF que pinta la barra (deshacer / rehacer). */
export interface HistoryFlags {
  canUndo: boolean;
  canRedo: boolean;
}

/** Lo que el visor (Viewer.svelte) hace con los avisos de las anotaciones. */
export interface AnnotationsHost {
  onHistory(state: HistoryFlags): void;
  /** Cambiaron las anotaciones: hay cambios sin guardar y Python aún no los tiene. */
  onChanged(): void;
  /** Cambió la selección (anotaciones de EmbedPDF). */
  onSelect(items: Annot[]): void;
  /** El documento de EmbedPDF ya tiene esos cambios (miniaturas). */
  onRendered(pages: number[]): void;
  setTool(tool: string): void;
}

/**
 * `register(orden, tema, documento)` del historial: apunta la orden y la ejecuta. Es privado en
 * EmbedPDF 2.15.1; `batch` y `_quietly` lo sustituyen un momento para juntar o no apuntar las
 * órdenes. Revisarlo al actualizar EmbedPDF.
 */
interface HistoryInternals {
  register(command: Command, topic: string, documentId?: string): void;
}

type Markup = 'highlight' | 'underline' | 'strikeout' | 'squiggly';
type TextEdit = 'insert' | 'replace';
type StyleKey = keyof AnnotationStyle;

const T = PdfAnnotationSubtype;
const TX = t.viewer.annotations;
// Marcas de texto: tipo de anotación, herramienta de EmbedPDF (sus valores) y color del estilo.
const MARKUP: Record<Markup, [PdfAnnotationSubtype, string, StyleKey]> = {
  highlight: [T.HIGHLIGHT, 'highlight', 'highlightColor'],
  underline: [T.UNDERLINE, 'underline', 'underlineColor'],
  strikeout: [T.STRIKEOUT, 'strikeout', 'strikeoutColor'],
  squiggly: [T.SQUIGGLY, 'squiggly', 'squigglyColor'],
};
// Insertar y reemplazar texto: marca de inserción (Caret) con el texto; al reemplazar, además,
// lo seleccionado se tacha y queda agrupado con la marca (como Acrobat).
const TEXT_EDITS: Record<TextEdit, { intent: string; title: string; label: string }> = {
  insert: { intent: 'Insert', title: TX.insertTitle, label: TX.insertLabel },
  replace: { intent: 'Replace', title: TX.replaceTitle, label: TX.replaceLabel },
};
// Tras crear con estas herramientas se pasa al puntero con lo creado seleccionado (como Qt).
const AUTO_POINTER = new Set<string>([
  TOOLS.RECT, TOOLS.ELLIPSE, TOOLS.LINE, TOOLS.ARROW, TOOLS.POLYLINE, TOOLS.POLYGON,
  TOOLS.TEXT, TOOLS.CALLOUT, TOOLS.NOTE, TOOLS.IMAGE, TOOLS.PLACE,
]);
// Fuera del orden de dibujo: no se apilan con las demás (enlaces, formularios, ventanas de nota).
const UNSTACKED = new Set<PdfAnnotationSubtype>([T.LINK, T.WIDGET, T.POPUP]);
const HISTORY_TOPIC = 'annotations'; // el de las órdenes de EmbedPDF (ANNOTATION_HISTORY_TOPIC)
// Caja del texto libre (_fitText): alto de línea (en tamaños de letra) y margen, en puntos.
const TEXT_LINE = 1.2;
const TEXT_PADDING = 6;

/** Estilo de `tool` (herramienta del visor) para los valores de su herramienta de EmbedPDF. */
function toolDefaults(tool: string, style: AnnotationStyle): Record<string, unknown> {
  switch (tool) {
    case TOOLS.RECT:
    case TOOLS.ELLIPSE:
    case TOOLS.POLYLINE:
    case TOOLS.POLYGON:
      return { strokeColor: style.shapeColor, strokeWidth: style.shapeWidth };
    case TOOLS.LINE:
    case TOOLS.ARROW:
      return { strokeColor: style.penColor, strokeWidth: style.shapeWidth };
    case TOOLS.PEN:
      return { strokeColor: style.penColor, strokeWidth: style.penWidth };
    case TOOLS.MARKER:
      return { strokeColor: style.highlightColor, strokeWidth: style.markerWidth };
    case TOOLS.DRAW:
      return { strokeColor: style.penColor, strokeWidth: style.thinWidth };
    case TOOLS.TEXT:
      return { fontColor: style.penColor, fontSize: style.fontSize };
    case TOOLS.CALLOUT:
      return { fontColor: style.penColor, fontSize: style.fontSize, strokeColor: style.penColor };
    case TOOLS.NOTE:
      return { strokeColor: style.noteColor, color: style.noteColor };
    case TOOLS.REDACT:
      return {
        color: style.redactColor, overlayColor: style.redactColor, strokeColor: style.redactOutline,
        contents: MANUAL_LABEL, subject: KINDS.MANUAL,
      };
    default:
      return {};
  }
}

export class Annotations {
  canvas: PageCanvas;
  host: AnnotationsHost;
  style: AnnotationStyle = { ...DEFAULT_STYLE };
  seen = new Set<string>(); // anotaciones ya creadas (rehacer no vuelve a pedir el texto de la nota)
  watchers = new Set<() => void>(); // avisar de cualquier cambio en las anotaciones (`watch`)
  measure: CanvasRenderingContext2D | null = null; // para medir el texto libre (_fitText)

  /** `host`: lo que el visor hace con los avisos. */
  constructor(canvas: PageCanvas, host: AnnotationsHost) {
    this.canvas = canvas;
    this.host = host;
    canvas.loading.then(() => this._connect());
  }

  /** `fn()` se llama con cada cambio en las anotaciones del documento a la vista; devuelve cómo dejar de avisar. */
  watch(fn: () => void): () => void {
    this.watchers.add(fn);
    return () => this.watchers.delete(fn);
  }

  /** Lo llama el lienzo al poner a la vista una versión nueva del documento (empieza sin historial). */
  documentShown(): void {
    this.seen.clear();
    this.host.onHistory({ canUndo: false, canRedo: false });
    this.host.onSelect([]);
    for (const fn of this.watchers) fn();
  }

  /** Lo llama el lienzo antes de activar la herramienta de anotación de `tool`: le da nuestro estilo. */
  applyStyle(tool: string): void {
    const id = (ANNOTATION_TOOL as Record<string, string | undefined>)[tool];
    if (id) this._plugin().provides().setToolDefaults(id, toolDefaults(tool, this.style));
  }

  // ── EmbedPDF ───────────────────────────────────────────────────────────
  _registry(): PluginRegistry {
    return this.canvas.registry!; // ya está: las anotaciones se usan después de `canvas.loading`
  }

  _plugin(): AnnotationPlugin {
    return this._registry().getPlugin<AnnotationPlugin>('annotation')!;
  }

  _historyPlugin(): HistoryPlugin {
    return this._registry().getPlugin<HistoryPlugin>('history')!;
  }

  /** El mismo complemento, con su `register` privado (ver HistoryInternals). */
  _historyInternals(): HistoryInternals {
    return this._historyPlugin() as unknown as HistoryInternals;
  }

  /** Las anotaciones del documento a la vista (null mientras no hay ninguno). */
  scope(): AnnotationScope | null {
    const shown: string | null = this.canvas.shown;
    return shown ? this._plugin().provides().forDocument(shown) : null;
  }

  _history(): HistoryScope {
    return this._historyPlugin().provides().forDocument(this.canvas.shown!);
  }

  /** Avisos del registro (compartido por todos los visores): solo los de nuestro documento. */
  _connect(): void {
    if (this.canvas.closed) return;
    const annotation = this._plugin().provides();
    const history = this._historyPlugin().provides();
    const ours = (documentId: string) => documentId === this.canvas.shown;
    this.canvas.unsubscribe.push(
      annotation.onAnnotationEvent((event) => {
        if (ours(event.documentId)) this._onEvent(event);
      }),
      annotation.onStateChange(({ documentId }) => {
        if (!ours(documentId)) return;
        this.host.onSelect(this.selected());
        for (const fn of this.watchers) fn();
      }),
      history.onHistoryChange(({ documentId, state }) => {
        if (ours(documentId)) this.host.onHistory(state.global);
      }),
      // Se dejó de colocar un sello o una firma sin crearlo (p. ej. con Esc): se vuelve a
      // seleccionar texto. Al crearlo, `_created` ya pasó al puntero (este aviso puede llegar
      // antes o después de la creación: por eso se mira en la siguiente vuelta).
      annotation.onActiveToolChange(({ documentId, tool }) => {
        if (!ours(documentId) || tool) return;
        setTimeout(() => {
          if (this.canvas.tool === TOOLS.PLACE) this.host.setTool(TOOLS.SELECT);
        });
      }),
    );
  }

  _onEvent(event: AnnotationEvent): void {
    if (event.type === 'loaded') return;
    // Cada cambio llega dos veces: al hacerlo (también al deshacer) y cuando ya está en el PDF.
    if (event.committed) {
      this.host.onRendered([event.pageIndex]);
      return;
    }
    this.host.onChanged();
    if (event.type === 'update' && 'contents' in event.patch && event.annotation.type === T.FREETEXT) {
      this._fitText(event.pageIndex, event.annotation.id);
    }
    if (event.type === 'create' && !this.seen.has(event.annotation.id)) {
      this.seen.add(event.annotation.id);
      this._created(event.annotation, event.pageIndex);
    }
  }

  /** Recién creada con una herramienta: la nota pide su texto y se vuelve al puntero (como Qt). */
  async _created(annotation: PdfAnnotationObject, pageIndex: number): Promise<void> {
    const { tool } = this.canvas;
    if (!AUTO_POINTER.has(tool)) return;
    const scope = this.scope();
    if (!scope) return;
    if (annotation.type === T.TEXT && tool === TOOLS.NOTE) {
      const text = (await askText(TX.noteTitle, TX.noteLabel, '', { multiline: true }))?.trim();
      if (!text) {
        scope.deleteAnnotation(pageIndex, annotation.id);
        return;
      }
      scope.updateAnnotation(pageIndex, annotation.id, { contents: text });
    }
    // El texto libre se queda editándose en la página: cambiar de herramienta no lo cierra.
    this.host.setTool(TOOLS.POINTER);
    scope.selectAnnotation(pageIndex, annotation.id);
  }

  /**
   * Al terminar de escribir un texto libre, su caja crece hasta que quepa todo: de ancho, la
   * línea más larga (sin pasar del borde de la página, entonces se parten las líneas); de alto,
   * todas las líneas. Nunca encoge: se respeta la caja que el usuario agrandó. Las cajas
   * giradas (texto derecho en páginas giradas) se dejan como están.
   */
  _fitText(pageIndex: number, id: string): void {
    const scope = this.scope();
    const object = scope?.getAnnotationById(id)?.object as Annot | undefined;
    if (!scope || !object || object.rotation || object.unrotatedRect) return;
    const { origin, size } = object.rect;
    const pageWidth: number = this.canvas.pageInfo(pageIndex).size.width;
    const room = Math.max(size.width, pageWidth - origin.x - TEXT_PADDING);
    const context = (this.measure ??= document.createElement('canvas').getContext('2d')!);
    context.font = `${object.fontSize}px Helvetica, Arial, sans-serif`;
    let width = 0;
    let lines = 0;
    for (const line of (object.contents ?? '').split('\n')) {
      const w = context.measureText(line).width + TEXT_PADDING;
      width = Math.max(width, Math.min(w, room));
      lines += Math.max(1, Math.ceil(w / room));
    }
    const height = lines * object.fontSize * TEXT_LINE + TEXT_PADDING;
    if (width <= size.width + 0.5 && height <= size.height + 0.5) return;
    const rect = { origin, size: { width: Math.max(width, size.width), height: Math.max(height, size.height) } };
    scope.updateAnnotation(pageIndex, id, { rect });
  }

  // ── Selección ──────────────────────────────────────────────────────────
  /** Anotaciones seleccionadas (objetos de EmbedPDF). */
  selected(): Annot[] {
    return this.scope()?.getSelectedAnnotations().map((tracked) => tracked.object as Annot) ?? [];
  }

  select(items: PdfAnnotationObject[]): void {
    this.scope()?.setSelection(items.map((item) => item.id));
  }

  clearSelection(): void {
    const scope = this.scope();
    if (scope?.getSelectedAnnotationIds().length) scope.deselectAnnotation();
  }

  // ── Cambios (cada uno se puede deshacer) ───────────────────────────────
  /** Aplica `change(objeto)` → cambios (o null) a cada anotación de `items`, en un solo paso. */
  update<A extends PdfAnnotationObject>(items: A[], change: (item: A) => Record<string, unknown> | null): void {
    const patches = items.map((item) => ({ pageIndex: item.pageIndex, id: item.id, patch: change(item) }))
      .filter((p): p is { pageIndex: number; id: string; patch: Partial<PdfAnnotationObject> } => Boolean(p.patch));
    if (patches.length) this.scope()?.updateAnnotations(patches);
  }

  /**
   * Lo que cree, cambie o borre `fn()` se deshace de una vez: las órdenes que EmbedPDF apunta en
   * su historial (una por anotación) se juntan en una.
   */
  batch(fn: () => void): void {
    const history = this._historyInternals();
    const { register } = history;
    const steps: { command: Command; topic: string; documentId?: string }[] = [];
    history.register = (command, topic, documentId) => {
      command.execute();
      steps.push({ command, topic, documentId });
    };
    try {
      fn();
    } finally {
      history.register = register;
    }
    if (!steps.length) return;
    let done = true; // ya hecho: el historial lo ejecuta al apuntarlo
    register.call(history, {
      execute: () => {
        if (!done) steps.forEach(({ command }) => command.execute());
        done = false;
      },
      undo: () => steps.toReversed().forEach(({ command }) => command.undo()),
      metadata: {
        annotationIds: steps.flatMap(({ command }) => (command.metadata as { annotationIds?: string[] } | undefined)?.annotationIds ?? []),
      },
    }, steps[0].topic, steps[0].documentId);
  }

  remove(items: PdfAnnotationObject[]): void {
    if (items.length) this.scope()?.deleteAnnotations(items.map((item) => ({ pageIndex: item.pageIndex, id: item.id })));
  }

  /**
   * Trae al frente (`front`) o envía al fondo las anotaciones `items` en su página. Se dibujan
   * en el orden de la página y EmbedPDF no sabe cambiarlo; solo se puede llevar una anotación
   * al final, borrándola y volviéndola a crear (con id nuevo: con el mismo, EmbedPDF descarta la
   * nueva mientras el borrado está pendiente). Así:
   *   · al frente: se llevan al final las elegidas;
   *   · al fondo: se llevan al final las que hay delante de ellas;
   *   · deshacer (EmbedPDF devolvería lo borrado al final, en otro orden): se vuelve a llevar al
   *     final todo lo que había desde la primera que se movió, en el orden de antes.
   * Los grupos (como reemplazar texto) se mueven enteros. Devuelve las nuevas de `items`, o null
   * si habría que volver a crear una imagen (su objeto no lleva la imagen).
   */
  async reorder(items: Annot[], front: boolean): Promise<Annot[] | null> {
    const scope = this.scope();
    if (!scope || !items.length) return items;
    const state = scope.getState();
    const chosen = new Set(items.map((item) => item.id));
    const moved: Annot[] = [];
    const restore: Annot[] = [];
    for (const pageIndex of new Set(items.map((item) => item.pageIndex))) {
      const page = (state.pages[pageIndex] ?? []).map((uid) => state.byUid[uid]?.object as Annot | undefined)
        .filter((object): object is Annot => Boolean(object) && !UNSTACKED.has(object!.type));
      const last = page.findLastIndex((object) => chosen.has(object.id));
      const some = withGroups(page, front
        ? page.filter((object) => chosen.has(object.id))
        : page.slice(0, last).filter((object) => !chosen.has(object.id)));
      if (!some.length) continue;
      moved.push(...some);
      restore.push(...withGroups(page, page.slice(page.indexOf(some[0]))));
    }
    if (!moved.length) return items;
    // Un sello (también una imagen o una firma escrita) se vuelve a crear con su dibujo: su objeto
    // no lo lleva, así que se exporta antes (un PDF de una página, como al colocarlo).
    const appearances = await this._appearances(restore.filter((object) => object.type === T.STAMP));
    if (!appearances) return null;
    const current = new Map<string, Annot>(); // id de antes -> objeto de ahora
    const now = (object: Annot) => current.get(object.id) ?? object;
    const toEnd = (objects: Annot[]) => this._quietly(() => {
      const live = objects.map(now);
      scope.deleteAnnotations(live.map(({ pageIndex, id }) => ({ pageIndex, id })));
      const ids = new Map(live.map((object) => [object.id, uuidV4()]));
      live.forEach((object, k) => {
        const copy: Annot = { ...object, id: ids.get(object.id)! };
        if (object.inReplyToId && ids.has(object.inReplyToId)) copy.inReplyToId = ids.get(object.inReplyToId);
        this.seen.add(copy.id); // no es de una herramienta
        const appearance = appearances.get(objects[k].id);
        // El contexto depende del tipo de anotación (el de un sello es su dibujo).
        scope.createAnnotation(object.pageIndex, copy, (appearance ? { appearance } : undefined) as never);
        current.set(objects[k].id, copy);
      });
    });
    this._historyInternals().register({ execute: () => toEnd(moved), undo: () => toEnd(restore) }, HISTORY_TOPIC, this.canvas.shown ?? undefined);
    return items.map(now);
  }

  /** Dibujo de cada sello (id → PDF de una página) o null si no se pudo exportar alguno. */
  async _appearances(stamps: Annot[]): Promise<Map<string, ArrayBuffer> | null> {
    const appearances = new Map<string, ArrayBuffer>();
    if (!stamps.length) return appearances;
    await this.commit(); // el dibujo sale del PDF de EmbedPDF
    const registry = this._registry();
    const doc = registry.getStore().getState().core.documents[this.canvas.shown!]?.document;
    if (!doc) return null;
    try {
      for (const stamp of stamps) {
        const pdf = await registry.getEngine().exportAnnotationAppearanceAsPdf(doc, doc.pages[stamp.pageIndex], stamp).toPromise();
        appearances.set(stamp.id, pdf);
      }
    } catch {
      return null;
    }
    return appearances;
  }

  /** Hace `fn()` sin que EmbedPDF apunte nada en su historial (quien llama apunta lo suyo). */
  _quietly(fn: () => void): void {
    const history = this._historyInternals();
    const { register } = history;
    history.register = (command) => command.execute();
    try {
      fn();
    } finally {
      history.register = register;
    }
  }

  /** Desplaza `items` (dx, dy) puntos en la página tal como se ve (flechas del teclado). */
  move(items: PdfAnnotationObject[], dx: number, dy: number): void {
    const scope = this.scope();
    if (!scope) return;
    for (const item of items) {
      const { rotation } = this.canvas.pageInfo(item.pageIndex);
      // De la página vista a la página sin girar (los cuartos de vuelta van en sentido horario).
      const [x, y] = [[dx, dy], [dy, -dx], [-dx, -dy], [-dy, dx]][rotation as number];
      scope.moveAnnotation(item.pageIndex, item.id, { x, y }, 'delta');
    }
  }

  /**
   * Sello de texto (leyenda) centrado en `at` (página vista): texto libre con marco del color y
   * fondo blanco, editable como cualquier texto libre. Mide lo mismo que su miniatura.
   */
  textStamp(stamp: TextStamp, at: { index: number; x: number; y: number }): Annot[] {
    const [pw, ph]: [number, number] = this.canvas.sizes[at.index];
    const size = textStampSize(stamp);
    const w = Math.min(pw, size.width);
    const h = Math.min(ph, size.height);
    const x0 = Math.max(0, Math.min(pw - w, at.x - w / 2));
    const y0 = Math.max(0, Math.min(ph - h, at.y - h / 2));
    const { rotation } = this.canvas.pageInfo(at.index);
    const annotation = applyInsertUpright({
      type: T.FREETEXT, pageIndex: at.index, rect: this.canvas.toPage(at.index, [x0, y0, x0 + w, y0 + h]),
      contents: stamp.text, fontSize: stamp.font_size, fontColor: stamp.color, fontFamily: PdfStandardFont.Helvetica_Bold,
      opacity: 1, textAlign: PdfTextAlignment.Center, verticalAlign: PdfVerticalAlignment.Middle,
      color: '#FFFFFF', backgroundColor: '#FFFFFF', strokeColor: stamp.color, strokeWidth: TEXT_STAMP.border,
    } as unknown as PdfAnnotationObject, rotation, true);
    return this.create([annotation as AnnotDraft]);
  }

  /** Crea anotaciones `[{ pageIndex, ...objeto }]`; devuelve las creadas (con su `id`). */
  create(items: AnnotDraft[]): Annot[] {
    const scope = this.scope();
    if (!scope) return [];
    return items.map(({ pageIndex, ...object }) => {
      const annotation = { ...object, pageIndex, id: uuidV4() } as Annot;
      this.seen.add(annotation.id); // no es de una herramienta: no se trata como tal
      scope.createAnnotation(pageIndex, annotation);
      return annotation;
    });
  }

  /**
   * Anota la selección de texto `parts` (`getFormattedSelection`): resalta, subraya, tacha,
   * ondula, o marca dónde insertar o qué reemplazar (`kind`: insert | replace, piden el texto).
   */
  markup(kind: Markup | TextEdit, parts: SelectionPart[]): Annot[] | Promise<Annot[]> {
    if (kind === 'insert' || kind === 'replace') return this._textEdit(kind, parts);
    const [type, toolId, styleKey] = MARKUP[kind];
    const color = this.style[styleKey];
    const defaults = this._plugin().provides().getTools().find((tool) => tool.id === toolId)?.defaults ?? {};
    return this.create(parts.map(({ pageIndex, rect, segmentRects }) => ({
      ...defaults, type, pageIndex, rect, segmentRects, strokeColor: color, color,
    })));
  }

  /**
   * Insertar o reemplazar texto: pide el texto y pone la marca de inserción al final de lo
   * seleccionado; al reemplazar, tacha lo seleccionado (agrupado con la marca: se mueven y
   * borran juntos). Como en la herramienta de EmbedPDF, la marca mide media línea.
   */
  async _textEdit(kind: TextEdit, parts: SelectionPart[]): Promise<Annot[]> {
    const { intent, title, label } = TEXT_EDITS[kind];
    const last = parts.at(-1);
    const line = last?.segmentRects.at(-1);
    if (!last || !line) return [];
    const text = (await askText(title, label, '', { multiline: true }))?.trim();
    if (!text) return [];
    const color = this.style.editColor;
    const common = { strokeColor: color, color, opacity: 1, flags: ['print'] };
    const size = line.size.height / 2;
    const [caret] = this.create([{
      ...common, type: T.CARET, pageIndex: last.pageIndex, intent, contents: text,
      rect: { origin: { x: line.origin.x + line.size.width - size / 2, y: line.origin.y + size }, size: { width: size, height: size } },
      rectangleDifferences: { left: 0.5, top: 0.5, right: 0.5, bottom: 0.5 },
    }]);
    if (kind === 'replace') {
      this.create(parts.map(({ pageIndex, rect, segmentRects }) => ({
        ...common, type: T.STRIKEOUT, pageIndex, rect, segmentRects, intent: 'StrikeOutTextEdit',
        inReplyToId: caret.id, replyType: PdfAnnotationReplyType.Group,
      })));
    }
    return [caret];
  }


  undo(): void {
    if (this.canvas.shown) this._history().undo();
  }

  redo(): void {
    if (this.canvas.shown) this._history().redo();
  }

  /**
   * Escribe en el PDF de EmbedPDF lo pendiente (para dibujar las páginas con las anotaciones al
   * día y antes de sacar una copia: document/copy.ts).
   */
  async commit(): Promise<void> {
    this.canvas.finishEditing(); // el texto que se está escribiendo también cuenta
    await this.scope()?.commit().toPromise();
  }
}

/** `some` (anotaciones de `page`) con los demás miembros de sus grupos, en el orden de la página. */
function withGroups(page: Annot[], some: Annot[]): Annot[] {
  const ids = new Set(some.map((object) => object.id));
  for (let grew = true; grew;) {
    grew = false;
    for (const object of page) {
      const linked = ids.has(object.id) ? object.inReplyToId : null;
      if (!ids.has(object.id) && object.inReplyToId && ids.has(object.inReplyToId)) {
        ids.add(object.id);
        grew = true;
      } else if (linked && !ids.has(linked) && page.some((other) => other.id === linked)) {
        ids.add(linked);
        grew = true;
      }
    }
  }
  return page.filter((object) => ids.has(object.id));
}
