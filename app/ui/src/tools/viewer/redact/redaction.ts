// Marcas de censura del visor (complemento Redaction de EmbedPDF, en modo anotación; paso 4
// de docs/web/embedpdf.md). Cada marca es una anotación Redact: se ve con borde rojo (al pasar
// el ratón, con el relleno que tendrá) y se revisa, se mueve, se borra y se deshace en la
// página como las demás anotaciones. La censura la aplica el motor de EmbedPDF en el documento del
// visor (apply.ts).
//
// Las marcas se agrupan por lo que las puso (su texto, /Contents) y por cómo (/Subj):
//   · texto y regex: un término de la lista (Python busca dónde aparece: redact.find);
//   · selección: lo seleccionado en la página (barra de la selección);
//   · manual: la herramienta «Marcar» (arrastrar sobre el texto o alrededor de un área).
import { PdfAnnotationSubtype, type PdfAnnotationObject, type PdfRedactAnnoObject, type Rect } from '@embedpdf/models';
import { t } from '$texts';
import type { Annotations } from '../annotations/annotations.ts';

/** Cómo se puso una marca (su /Subj). Son datos del PDF, no textos de la interfaz. */
export const KINDS = { TEXT: 'texto', REGEX: 'regex', SELECTION: 'selección', MANUAL: 'manual' } as const;
export type Kind = (typeof KINDS)[keyof typeof KINDS];

export const MANUAL_LABEL = t.viewer.redact.manualLabel;
const ALL_KINDS = new Set<string>(Object.values(KINDS));
const TERM_KINDS = new Set<string>([KINDS.TEXT, KINDS.REGEX]);
const MAX_LABEL = 40; // caracteres del nombre de una selección

/** Rectángulo `[x0, y0, x1, y1]` (página sin girar). */
type Box = [number, number, number, number];

/** Marcas que puso lo mismo: un término, una selección o la herramienta «Marcar». */
export interface RedactGroup {
  key: string;
  label: string;
  kind: Kind;
  marks: PdfRedactAnnoObject[];
  pages: number; // cuántas páginas tocan
}

/** Coincidencias de un término: respuesta de `redact.find`. */
export interface FindResult {
  term: string;
  kind: Kind;
  matches: { page: number; rect: Box }[];
}

/** Parte de una selección de texto (`getFormattedSelection` de EmbedPDF). */
export interface SelectionPart {
  pageIndex: number;
  rect: Rect;
  segmentRects: Rect[];
}

const rect = ([x0, y0, x1, y1]: Box): Rect => ({ origin: { x: x0, y: y0 }, size: { width: x1 - x0, height: y1 - y0 } });

export class RedactionMarks {
  annotations: Annotations;

  constructor(annotations: Annotations) {
    this.annotations = annotations;
  }

  get color(): string {
    return this.annotations.style.redactColor;
  }

  /** Las marcas del documento a la vista (objetos de EmbedPDF). */
  all(): PdfRedactAnnoObject[] {
    const scope = this.annotations.scope();
    if (!scope) return [];
    return Object.values(scope.getState().byUid).map((tracked) => (tracked as { object: PdfAnnotationObject }).object)
      .filter((object): object is PdfRedactAnnoObject => object.type === PdfAnnotationSubtype.REDACT);
  }

  /** Las marcas agrupadas, en el orden en que se pusieron. */
  groups(): RedactGroup[] {
    const groups = new Map<string, Omit<RedactGroup, 'pages'>>();
    for (const mark of this.all()) {
      const kind = (ALL_KINDS.has(mark.subject ?? '') ? mark.subject : KINDS.MANUAL) as Kind;
      const label = mark.contents || MANUAL_LABEL;
      const key = `${kind}\n${label}`;
      if (!groups.has(key)) groups.set(key, { key, label, kind, marks: [] });
      groups.get(key)!.marks.push(mark);
    }
    return [...groups.values()].map((group) => ({ ...group, pages: new Set(group.marks.map((m) => m.pageIndex)).size }));
  }

  /** Términos (texto y regex) de la lista, para buscarlos de nuevo o guardarlos en un perfil. */
  terms(): string[] {
    return this.groups().filter((group) => TERM_KINDS.has(group.kind)).map((group) => group.label);
  }

  /**
   * Marca lo que encontró `redact.find` (página sin girar). Quita antes las marcas de `replace`
   * (términos que se buscan de nuevo). Todo se deshace de una vez.
   */
  addMatches(results: FindResult[], replace: string[] = []): void {
    const old = this.groups().filter((group) => replace.includes(group.label) && TERM_KINDS.has(group.kind));
    this.annotations.batch(() => {
      this.annotations.remove(old.flatMap((group) => group.marks));
      this.annotations.create(results.flatMap(({ term, kind, matches }) => matches.map(({ page, rect: box }) => (
        this._mark(page, rect(box), [rect(box)], term, kind)))));
    });
  }

  /** Marca la selección de texto `parts` (`getFormattedSelection`), con su texto como nombre. */
  addSelection(text: string, parts: SelectionPart[]): void {
    let label = text.split(/\s+/).join(' ').trim() || t.viewer.redact.selectionLabel;
    if (label.length > MAX_LABEL) label = `${label.slice(0, MAX_LABEL - 1)}…`;
    this.annotations.batch(() => this.annotations.create(parts.map(({ pageIndex, rect: box, segmentRects }) => (
      this._mark(pageIndex, box, segmentRects, label, KINDS.SELECTION)))));
  }

  remove(marks: PdfAnnotationObject[]): void {
    this.annotations.remove(marks);
  }

  /** Color del relleno: el de las marcas nuevas y el de todas las que ya hay. */
  setColor(color: string): void {
    this.annotations.style.redactColor = color;
    this.annotations.update(this.all(), () => ({ color, overlayColor: color }));
  }

  _mark(pageIndex: number, box: Rect, segmentRects: Rect[], label: string, kind: Kind) {
    const { redactColor: color, redactOutline } = this.annotations.style;
    return {
      type: PdfAnnotationSubtype.REDACT, pageIndex, rect: box, segmentRects,
      contents: label, subject: kind, color, overlayColor: color, strokeColor: redactOutline, opacity: 1,
    };
  }
}
