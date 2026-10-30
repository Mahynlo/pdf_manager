// Marcas de censura del visor (complemento Redaction de EmbedPDF, en modo anotación; paso 4
// de docs/web/embedpdf.md). Cada marca es una anotación Redact: se ve con borde rojo (al pasar
// el ratón, con el relleno que tendrá) y se revisa, se mueve, se borra y se deshace en la
// página como las demás anotaciones. La censura la aplica Python (redact.apply) con las marcas
// que recibe al sincronizar.
//
// Las marcas se agrupan por lo que las puso (su texto, /Contents) y por cómo (/Subj):
//   · texto y regex: un término de la lista (Python busca dónde aparece: redact.find);
//   · selección: lo seleccionado en la página (barra de la selección);
//   · manual: la herramienta «Marcar» (arrastrar sobre el texto o alrededor de un área).
import { PdfAnnotationSubtype } from '@embedpdf/models';

export const KINDS = { TEXT: 'texto', REGEX: 'regex', SELECTION: 'selección', MANUAL: 'manual' };
export const MANUAL_LABEL = 'Marcado a mano';
const ALL_KINDS = new Set(Object.values(KINDS));
const TERM_KINDS = new Set([KINDS.TEXT, KINDS.REGEX]);
const MAX_LABEL = 40; // caracteres del nombre de una selección

const rect = ([x0, y0, x1, y1]) => ({ origin: { x: x0, y: y0 }, size: { width: x1 - x0, height: y1 - y0 } });

export class RedactionMarks {
  /** @param {import('./annotations.js').Annotations} annotations */
  constructor(annotations) {
    this.annotations = annotations;
  }

  get color() {
    return this.annotations.style.redactColor;
  }

  /** Las marcas del documento a la vista (objetos de EmbedPDF). */
  all() {
    const scope = this.annotations.scope();
    if (!scope) return [];
    return Object.values(scope.getState().byUid).map((tracked) => tracked.object)
      .filter((object) => object.type === PdfAnnotationSubtype.REDACT);
  }

  /**
   * Las marcas agrupadas, en el orden en que se pusieron:
   * `[{ key, label, kind, marks, pages }]` (`pages`: cuántas páginas tocan).
   */
  groups() {
    const groups = new Map();
    for (const mark of this.all()) {
      const kind = ALL_KINDS.has(mark.subject) ? mark.subject : KINDS.MANUAL;
      const label = mark.contents || MANUAL_LABEL;
      const key = `${kind}\n${label}`;
      if (!groups.has(key)) groups.set(key, { key, label, kind, marks: [] });
      groups.get(key).marks.push(mark);
    }
    return [...groups.values()].map((group) => ({ ...group, pages: new Set(group.marks.map((m) => m.pageIndex)).size }));
  }

  /** Términos (texto y regex) de la lista, para buscarlos de nuevo o guardarlos en un perfil. */
  terms() {
    return this.groups().filter((group) => TERM_KINDS.has(group.kind)).map((group) => group.label);
  }

  /**
   * Marca lo que encontró `redact.find`: `[{ term, kind, matches: [{ page, rect }] }]` (página
   * sin girar). Quita antes las marcas de `replace` (términos que se buscan de nuevo). Todo se
   * deshace de una vez.
   */
  addMatches(results, replace = []) {
    const old = this.groups().filter((group) => replace.includes(group.label) && TERM_KINDS.has(group.kind));
    this.annotations.batch(() => {
      this.annotations.remove(old.flatMap((group) => group.marks));
      this.annotations.create(results.flatMap(({ term, kind, matches }) => matches.map(({ page, rect: box }) => (
        this._mark(page, rect(box), [rect(box)], term, kind)))));
    });
  }

  /** Marca la selección de texto `parts` (`getFormattedSelection`), con su texto como nombre. */
  addSelection(text, parts) {
    let label = text.split(/\s+/).join(' ').trim() || 'Selección';
    if (label.length > MAX_LABEL) label = `${label.slice(0, MAX_LABEL - 1)}…`;
    this.annotations.batch(() => this.annotations.create(parts.map(({ pageIndex, rect: box, segmentRects }) => (
      this._mark(pageIndex, box, segmentRects, label, KINDS.SELECTION)))));
  }

  remove(marks) {
    this.annotations.remove(marks);
  }

  /** Color del relleno: el de las marcas nuevas y el de todas las que ya hay. */
  setColor(color) {
    this.annotations.style.redactColor = color;
    this.annotations.update(this.all(), () => ({ color, overlayColor: color }));
  }

  _mark(pageIndex, box, segmentRects, label, kind) {
    const { redactColor: color, redactOutline } = this.annotations.style;
    return {
      type: PdfAnnotationSubtype.REDACT, pageIndex, rect: box, segmentRects,
      contents: label, subject: kind, color, overlayColor: color, strokeColor: redactOutline, opacity: 1,
    };
  }
}
