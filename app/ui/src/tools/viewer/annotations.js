// Anotaciones del visor (equivale a canvas/items y annotation_io.py en Qt) con el
// complemento Annotation de EmbedPDF (paso 4 de docs/web/embedpdf.md).
//
// EmbedPDF las dibuja (su capa en PdfPage.svelte), las selecciona, las mueve y redimensiona,
// edita el texto libre en la página y crea las nuevas con sus herramientas (rectángulo,
// círculo, línea, flecha, polilínea, polígono, pluma, marcador, texto libre, llamada, nota e
// imagen: las activa canvas.js). Su historial da deshacer y rehacer. Aquí está lo nuestro:
//   · el estilo de cada visor (colores y grosores), que se da a la herramienta al activarla;
//   · las anotaciones de la selección de texto: resaltar, subrayar, tachar, ondulado, insertar
//     y reemplazar texto (estas dos piden el texto); y los sellos y leyendas;
//   · tras dibujar una forma, el texto, la llamada, la nota o la imagen, volver al puntero con
//     ella seleccionada (como Qt); la nota pide antes su texto;
//   · juntar en un solo paso de deshacer lo que se crea a la vez (`batch`: p. ej. las marcas de
//     censura de un término, ver redaction.js);
//   · traer al frente y enviar al fondo (`reorder`), que EmbedPDF no sabe hacer;
//   · pasar las anotaciones a Python (`sync`) antes de guardar, imprimir o cambiar las
//     páginas: se sube la copia de EmbedPDF y Python toma de ella las anotaciones
//     (viewer.sync_annotations). Y avisarle de que hay cambios sin guardar.
//
// Las coordenadas de EmbedPDF son de la página sin girar (canvas.toView / toPage las pasan
// a las de la página tal como se ve).
import {
  PdfAnnotationReplyType, PdfAnnotationSubtype, PdfStandardFont, PdfTextAlignment, PdfVerticalAlignment, uuidV4,
} from '@embedpdf/models';
import { applyInsertUpright } from '@embedpdf/plugin-annotation';
import { call } from '$lib/api.js';
import { askText } from '$lib/ui.js';
import { ANNOTATION_TOOL, TOOLS } from './canvas.js';
import { DEFAULT_STYLE } from './palette.js';
import { KINDS, MANUAL_LABEL } from './redaction.js';

const T = PdfAnnotationSubtype;
// Marcas de texto: tipo de anotación, herramienta de EmbedPDF (sus valores) y color del estilo.
const MARKUP = {
  highlight: [T.HIGHLIGHT, 'highlight', 'highlightColor'],
  underline: [T.UNDERLINE, 'underline', 'underlineColor'],
  strikeout: [T.STRIKEOUT, 'strikeout', 'strikeoutColor'],
  squiggly: [T.SQUIGGLY, 'squiggly', 'squigglyColor'],
};
// Insertar y reemplazar texto: marca de inserción (Caret) con el texto; al reemplazar, además,
// lo seleccionado se tacha y queda agrupado con la marca (como Acrobat).
const TEXT_EDITS = {
  insert: { intent: 'Insert', title: 'Insertar texto', label: 'Texto a insertar:' },
  replace: { intent: 'Replace', title: 'Reemplazar texto', label: 'Texto nuevo:' },
};
// Tras crear con estas herramientas se pasa al puntero con lo creado seleccionado (como Qt).
const AUTO_POINTER = new Set([
  TOOLS.RECT, TOOLS.ELLIPSE, TOOLS.LINE, TOOLS.ARROW, TOOLS.POLYLINE, TOOLS.POLYGON,
  TOOLS.TEXT, TOOLS.CALLOUT, TOOLS.NOTE, TOOLS.IMAGE,
]);
// Sello (como add_stamp_legend en Qt): texto centrado con marco, sobre blanco.
const STAMP = { minWidth: 105, minHeight: 29, border: 1.5, padding: 16 };
const NOTE_TITLE = 'Añadir Nota de Texto';
// Fuera del orden de dibujo: no se apilan con las demás (enlaces, formularios, ventanas de nota).
const UNSTACKED = new Set([T.LINK, T.WIDGET, T.POPUP]);
const HISTORY_TOPIC = 'annotations'; // el de las órdenes de EmbedPDF (ANNOTATION_HISTORY_TOPIC)
// Caja del texto libre (_fitText): alto de línea (en tamaños de letra) y margen, en puntos.
const TEXT_LINE = 1.2;
const TEXT_PADDING = 6;

/** Estilo de `tool` (herramienta del visor) para los valores de su herramienta de EmbedPDF. */
function toolDefaults(tool, style) {
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
  /**
   * @param {import('./canvas.js').PageCanvas} canvas
   * @param {number} docId documento del servicio "viewer"
   * @param {{ onHistory: (state) => void, onChanged: () => void, onSelect: (items) => void,
   *   onRendered: (pages) => void, setTool: (tool) => void }} host
   *   `onHistory({ canUndo, canRedo })`; `onChanged()`: hay cambios sin guardar; `onSelect(items)`:
   *   cambió la selección (anotaciones de EmbedPDF); `onRendered(páginas)`: el documento de
   *   EmbedPDF ya tiene esos cambios (miniaturas); `setTool(t)`: cambiar de herramienta.
   */
  constructor(canvas, docId, host) {
    this.canvas = canvas;
    this.docId = docId;
    this.host = host;
    this.style = { ...DEFAULT_STYLE };
    this.version = 0; // cambios hechos en el documento a la vista
    this.synced = 0; // `version` que ya tiene Python
    this.seen = new Set(); // anotaciones ya creadas (rehacer no vuelve a pedir el texto de la nota)
    this.watchers = new Set(); // avisar de cualquier cambio en las anotaciones (`watch`)
    canvas.loading.then(() => this._connect());
  }

  /** `fn()` se llama con cada cambio en las anotaciones del documento a la vista; devuelve cómo dejar de avisar. */
  watch(fn) {
    this.watchers.add(fn);
    return () => this.watchers.delete(fn);
  }

  /** Lo llama el lienzo al poner a la vista una versión nueva (viene de Python: ya la tiene). */
  documentShown() {
    this.version = 0;
    this.synced = 0;
    this.seen.clear();
    this.host.onHistory({ canUndo: false, canRedo: false });
    this.host.onSelect([]);
    for (const fn of this.watchers) fn();
  }

  /** Lo llama el lienzo antes de activar la herramienta de anotación de `tool`: le da nuestro estilo. */
  applyStyle(tool) {
    const id = ANNOTATION_TOOL[tool];
    if (id) this._plugin().provides().setToolDefaults(id, toolDefaults(tool, this.style));
  }

  // ── EmbedPDF ───────────────────────────────────────────────────────────
  _plugin() {
    return this.canvas.registry.getPlugin('annotation');
  }

  /** Las anotaciones del documento a la vista (null mientras no hay ninguno). */
  scope() {
    const { shown } = this.canvas;
    return shown ? this._plugin().provides().forDocument(shown) : null;
  }

  _history() {
    return this.canvas.registry.getPlugin('history').provides().forDocument(this.canvas.shown);
  }

  /** Avisos del registro (compartido por todos los visores): solo los de nuestro documento. */
  _connect() {
    if (this.canvas.closed) return;
    const annotation = this._plugin().provides();
    const history = this.canvas.registry.getPlugin('history').provides();
    const ours = (documentId) => documentId === this.canvas.shown;
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
    );
  }

  _onEvent(event) {
    if (event.type === 'loaded') return;
    // Cada cambio llega dos veces: al hacerlo (también al deshacer) y cuando ya está en el PDF.
    if (event.committed) {
      this.host.onRendered([event.pageIndex]);
      return;
    }
    this.version++;
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
  async _created(annotation, pageIndex) {
    const { tool } = this.canvas;
    if (!AUTO_POINTER.has(tool)) return;
    const scope = this.scope();
    if (annotation.type === T.TEXT && tool === TOOLS.NOTE) {
      const text = (await askText(NOTE_TITLE, 'Texto de la nota:', '', { multiline: true }))?.trim();
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
  _fitText(pageIndex, id) {
    const scope = this.scope();
    const object = scope?.getAnnotationById(id)?.object;
    if (!object || object.rotation || object.unrotatedRect) return;
    const { origin, size } = object.rect;
    const pageWidth = this.canvas.pageInfo(pageIndex).size.width;
    const room = Math.max(size.width, pageWidth - origin.x - TEXT_PADDING);
    const context = (this.measure ??= document.createElement('canvas').getContext('2d'));
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
  selected() {
    return this.scope()?.getSelectedAnnotations().map((tracked) => tracked.object) ?? [];
  }

  select(items) {
    this.scope()?.setSelection(items.map((item) => item.id));
  }

  clearSelection() {
    const scope = this.scope();
    if (scope?.getSelectedAnnotationIds().length) scope.deselectAnnotation();
  }

  // ── Cambios (cada uno se puede deshacer) ───────────────────────────────
  /** Aplica `change(objeto)` → cambios (o null) a cada anotación de `items`, en un solo paso. */
  update(items, change) {
    const patches = items.map((item) => ({ pageIndex: item.pageIndex, id: item.id, patch: change(item) }))
      .filter((p) => p.patch);
    if (patches.length) this.scope().updateAnnotations(patches);
  }

  /**
   * Lo que cree, cambie o borre `fn()` se deshace de una vez: las órdenes que EmbedPDF apunta en
   * su historial (una por anotación) se juntan en una.
   */
  batch(fn) {
    const history = this.canvas.registry.getPlugin('history');
    const { register } = history;
    const steps = [];
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
      metadata: { annotationIds: steps.flatMap(({ command }) => command.metadata?.annotationIds ?? []) },
    }, steps[0].topic, steps[0].documentId);
  }

  remove(items) {
    if (items.length) this.scope().deleteAnnotations(items.map((item) => ({ pageIndex: item.pageIndex, id: item.id })));
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
  reorder(items, front) {
    const scope = this.scope();
    if (!scope || !items.length) return items;
    const state = scope.getState();
    const chosen = new Set(items.map((item) => item.id));
    const moved = [];
    const restore = [];
    for (const pageIndex of new Set(items.map((item) => item.pageIndex))) {
      const page = (state.pages[pageIndex] ?? []).map((uid) => state.byUid[uid]?.object)
        .filter((object) => object && !UNSTACKED.has(object.type));
      const last = page.findLastIndex((object) => chosen.has(object.id));
      const some = withGroups(page, front
        ? page.filter((object) => chosen.has(object.id))
        : page.slice(0, last).filter((object) => !chosen.has(object.id)));
      if (!some.length) continue;
      moved.push(...some);
      restore.push(...withGroups(page, page.slice(page.indexOf(some[0]))));
    }
    if (!moved.length) return items;
    if (restore.some((object) => object.type === T.STAMP)) return null;
    const current = new Map(); // id de antes -> objeto de ahora
    const now = (object) => current.get(object.id) ?? object;
    const toEnd = (objects) => this._quietly(() => {
      const live = objects.map(now);
      scope.deleteAnnotations(live.map(({ pageIndex, id }) => ({ pageIndex, id })));
      const ids = new Map(live.map((object) => [object.id, uuidV4()]));
      live.forEach((object, k) => {
        const copy = { ...object, id: ids.get(object.id) };
        if (ids.has(object.inReplyToId)) copy.inReplyToId = ids.get(object.inReplyToId);
        this.seen.add(copy.id); // no es de una herramienta
        scope.createAnnotation(object.pageIndex, copy);
        current.set(objects[k].id, copy);
      });
    });
    const history = this.canvas.registry.getPlugin('history');
    history.register({ execute: () => toEnd(moved), undo: () => toEnd(restore) }, HISTORY_TOPIC, this.canvas.shown);
    return items.map(now);
  }

  /** Hace `fn()` sin que EmbedPDF apunte nada en su historial (quien llama apunta lo suyo). */
  _quietly(fn) {
    const history = this.canvas.registry.getPlugin('history');
    const { register } = history;
    history.register = (command) => command.execute();
    try {
      fn();
    } finally {
      history.register = register;
    }
  }

  /** Desplaza `items` (dx, dy) puntos en la página tal como se ve (flechas del teclado). */
  move(items, dx, dy) {
    const scope = this.scope();
    for (const item of items) {
      const { rotation } = this.canvas.pageInfo(item.pageIndex);
      // De la página vista a la página sin girar (los cuartos de vuelta van en sentido horario).
      const [x, y] = [[dx, dy], [dy, -dx], [-dx, -dy], [-dy, dx]][rotation];
      scope.moveAnnotation(item.pageIndex, item.id, { x, y }, 'delta');
    }
  }

  /** Crea anotaciones `[{ pageIndex, ...objeto }]`; devuelve las creadas (con su `id`). */
  create(items) {
    const scope = this.scope();
    if (!scope) return [];
    return items.map(({ pageIndex, ...object }) => {
      const annotation = { ...object, pageIndex, id: uuidV4() };
      this.seen.add(annotation.id); // no es de una herramienta: no se trata como tal
      scope.createAnnotation(pageIndex, annotation);
      return annotation;
    });
  }

  /**
   * Anota la selección de texto `parts` (`getFormattedSelection`): resalta, subraya, tacha,
   * ondula, o marca dónde insertar o qué reemplazar (`kind`: insert | replace, piden el texto).
   */
  markup(kind, parts) {
    if (TEXT_EDITS[kind]) return this._textEdit(kind, parts);
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
  async _textEdit(kind, parts) {
    const { intent, title, label } = TEXT_EDITS[kind];
    const last = parts.at(-1);
    const line = last?.segmentRects.at(-1);
    if (!line) return [];
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

  /** Sello o leyenda: texto libre centrado en `at` (página vista), con marco y fondo blanco. */
  stamp({ text, color, font_size: size }, at) {
    const [pw, ph] = this.canvas.sizes[at.index];
    const lines = text.split('\n');
    const longest = Math.max(...lines.map((line) => line.length));
    const w = Math.min(pw, Math.max(STAMP.minWidth, longest * size * 0.62 + STAMP.padding));
    const h = Math.min(ph, Math.max(STAMP.minHeight, lines.length * size * 1.25 + 12));
    const x0 = Math.max(0, Math.min(pw - w, at.x - w / 2));
    const y0 = Math.max(0, Math.min(ph - h, at.y - h / 2));
    const { rotation } = this.canvas.pageInfo(at.index);
    const annotation = applyInsertUpright({
      type: T.FREETEXT, pageIndex: at.index, rect: this.canvas.toPage(at.index, [x0, y0, x0 + w, y0 + h]),
      contents: text, fontSize: size, fontColor: color, fontFamily: PdfStandardFont.Helvetica, opacity: 1,
      textAlign: PdfTextAlignment.Center, verticalAlign: PdfVerticalAlignment.Middle,
      color: '#FFFFFF', backgroundColor: '#FFFFFF', strokeColor: color, strokeWidth: STAMP.border,
    }, rotation, true);
    return this.create([annotation]);
  }

  undo() {
    if (this.canvas.shown) this._history().undo();
  }

  redo() {
    if (this.canvas.shown) this._history().redo();
  }

  /** Escribe en el PDF de EmbedPDF lo pendiente (para dibujar las páginas con las anotaciones al día). */
  async commit() {
    this.canvas.finishEditing(); // el texto que se está escribiendo también cuenta
    await this.scope()?.commit().toPromise();
  }

  // ── Python ─────────────────────────────────────────────────────────────
  /**
   * Pasa a Python las anotaciones si cambiaron desde la última vez: sube la copia del
   * documento de EmbedPDF y Python toma de ella las anotaciones. Llamarlo antes de todo lo
   * que necesita el documento al día en Python. Resuelve `{ modified }` o null si no hacía falta.
   */
  async sync() {
    this.canvas.finishEditing(); // el texto que se está escribiendo también cuenta
    const documentId = this.canvas.shown;
    const version = this.version;
    if (!documentId || version === this.synced) return null;
    const plugin = this._plugin().provides().forDocument(documentId);
    await plugin.commit().toPromise(); // lo pendiente, ya escrito en el PDF de EmbedPDF
    const buffer = await this.canvas.registry.getPlugin('export').provides().forDocument(documentId).saveAsCopy().toPromise();
    const url = await call('viewer.upload_url');
    const response = await fetch(url, { method: 'POST', body: buffer });
    if (!response.ok) throw new Error(`No se pudo pasar el documento a Python (${response.status})`);
    const result = await call('viewer.sync_annotations', this.docId, url);
    if (documentId === this.canvas.shown) this.synced = Math.max(this.synced, version);
    return result;
  }
}

/** `some` (anotaciones de `page`) con los demás miembros de sus grupos, en el orden de la página. */
function withGroups(page, some) {
  const ids = new Set(some.map((object) => object.id));
  for (let grew = true; grew;) {
    grew = false;
    for (const object of page) {
      const linked = ids.has(object.id) ? object.inReplyToId : null;
      if (!ids.has(object.id) && ids.has(object.inReplyToId)) {
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
