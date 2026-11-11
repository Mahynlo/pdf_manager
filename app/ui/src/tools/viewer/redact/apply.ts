// Aplicar la censura en el documento del visor, de forma irreversible: el motor de EmbedPDF borra lo
// que tapan las marcas (`applyAllRedactions`, en su documento: no se vuelve a abrir), también el
// texto invisible del OCR, y Python borra las palabras del OCR que tapaban (`redact.apply`). Las
// páginas censuradas cambian de clave (sube su revisión) y su texto vuelve a leerse.
import { call } from '$lib/api.ts';
import type { Box } from '$lib/pdf-engine/index.ts';
import type { DocumentState } from '$lib/types.ts';
import type { PageCanvas } from '../canvas/canvas.ts';
import { registry } from '../canvas/embed.ts';
import type { PageEditor } from '../document/pages.ts';
import type { DocumentText } from '../document/text.ts';
import type { RedactionMarks } from './redaction.ts';

/** Lo que necesita: el documento a la vista, sus páginas, su texto en Python y sus marcas. */
export interface RedactionContext {
  docId: number;
  canvas: PageCanvas;
  pages: PageEditor;
  text: DocumentText;
  marks: RedactionMarks;
  /** Escribe en el documento de EmbedPDF las anotaciones pendientes (las marcas). */
  commit: () => Promise<void>;
}

/** El resultado: el estado del documento que da Python y cuántas marcas se aplicaron. */
export interface RedactionDone {
  state: Pick<DocumentState, 'modified' | 'annotated' | 'redacted'>;
  count: number;
}

/** Aplica las marcas del documento; null si no hay ninguna. */
export async function applyMarks({ docId, canvas, pages, text, marks, commit }: RedactionContext): Promise<RedactionDone | null> {
  const all = marks.all();
  if (!all.length) return null;
  const rects = new Map<number, Box[]>(); // página -> rectángulos de sus marcas (página sin girar)
  for (const { pageIndex, rect } of all) {
    const box: Box = [rect.origin.x, rect.origin.y, rect.origin.x + rect.size.width, rect.origin.y + rect.size.height];
    rects.set(pageIndex, [...(rects.get(pageIndex) ?? []), box]);
  }
  const indices = [...rects.keys()];
  await text.sync(indices); // Python necesita las medidas de esas páginas para sus palabras del OCR
  await commit();

  const doc = canvas.shownDocument();
  const engine = (await registry()).getEngine();
  for (const index of indices) await engine.applyAllRedactions(doc, doc.pages[index]).toPromise();

  const before = canvas.keys;
  const after = pages.revisedKeys(indices);
  const state = await call<RedactionDone['state']>('redact.apply', docId,
    indices.map((index) => ({ before: before[index], after: after[index], rects: rects.get(index) })));
  await pages.contentChanged(indices);
  text.changed();
  return { state, count: all.length };
}
