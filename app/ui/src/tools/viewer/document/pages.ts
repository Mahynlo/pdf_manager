// Las páginas del documento del visor: girar, insertar, duplicar, borrar y mover, y deshacerlo.
// Las hace el motor de EmbedPDF en el documento abierto (lib/pdf-engine) y el lienzo las muestra
// sin volver a abrirlo (canvas.showPages). Python recibe la nueva estructura (las claves de página,
// text.ts `sync`) antes de lo que la necesita.
//
// Cada página tiene una clave `uid:giro:revisión`: `uid` la identifica aunque cambie de sitio
// (los da este módulo a las páginas nuevas; con él Python guarda el texto del OCR de cada
// página), el giro va en grados y la revisión sube al censurarla (cambia su imagen).
import type { PdfBookmarkObject, PdfDocumentObject, PdfPageObject } from '@embedpdf/models';
import type { PageStructure } from '$lib/pdf-engine/index.ts';
import type { TocEntry } from '$lib/types.ts';
import type { PageCanvas } from '../canvas/canvas.ts';
import { registry, structure } from '../canvas/embed.ts';

const UNDO_LIMIT = 30; // operaciones de página que se pueden deshacer

interface PageKey {
  uid: number;
  rotation: number; // grados
  revision: number;
}

const parseKey = (key: string): PageKey => {
  const [uid, rotation, revision] = key.split(':').map(Number);
  return { uid, rotation, revision };
};
const formatKey = ({ uid, rotation, revision }: PageKey) => `${uid}:${rotation}:${revision}`;

/** El `uid` de cada página (Python los necesita con la copia del documento). */
export const pageUids = (keys: string[]) => keys.map((key) => parseKey(key).uid);

/** El giro de la página de clave `key`, en grados. */
export const pageRotation = (key: string) => parseKey(key).rotation;

/** Lo que dice si la estructura cambió: qué página va en cada sitio y con qué giro. */
const layoutOf = (keys: string[]) => keys.map((key) => key.split(':').slice(0, 2).join(':')).join(',');

/** Una operación hecha, con lo necesario para deshacerla y rehacerla. */
interface Step {
  redo(): Promise<void>;
  undo(): Promise<void>;
  page: number; // a qué página ir después de hacerla
  undoPage: number; // y después de deshacerla
  dispose?(): void; // suelta lo que guarda (la página borrada)
}

/** Cambio en el motor: devuelve las páginas que quedan. */
type EngineChange = (engine: PageStructure, doc: PdfDocumentObject) => Promise<PdfPageObject[]>;

export class PageEditor {
  private done: Step[] = [];
  private undone: Step[] = [];
  private nextUid: number;
  private savedLayout: string;

  constructor(private canvas: PageCanvas) {
    this.nextUid = Math.max(0, ...canvas.keys.map((key) => parseKey(key).uid)) + 1;
    this.savedLayout = layoutOf(canvas.keys);
  }

  get canUndo(): boolean {
    return this.done.length > 0;
  }

  get canRedo(): boolean {
    return this.undone.length > 0;
  }

  /** Clave de cada página, en orden. */
  get keys(): string[] {
    return this.canvas.keys;
  }

  /** Tamaño con que se ve cada página, en puntos. */
  get sizes(): [number, number][] {
    return this.canvas.sizes;
  }

  /** Con las páginas `keys`, la estructura no sería la guardada (páginas añadidas, quitadas, movidas o giradas). */
  changedWith(keys: string[] = this.canvas.keys): boolean {
    return layoutOf(keys) !== this.savedLayout;
  }

  /** Se guardó el documento: la estructura actual pasa a ser la guardada. */
  markSaved(): void {
    this.savedLayout = layoutOf(this.canvas.keys);
  }

  // ── Operaciones (cada una devuelve la página a la que ir) ─────────────
  /** Gira `indices` `angle` grados (múltiplo de 90; negativo: a la izquierda). */
  rotate(indices: number[], angle: number, page: number): Promise<number> {
    const turn = (degrees: number) => (keys: string[]) => keys.map((key, i) => {
      if (!indices.includes(i)) return key;
      const parsed = parseKey(key);
      return formatKey({ ...parsed, rotation: (((parsed.rotation + degrees) % 360) + 360) % 360 });
    });
    return this.record({
      redo: () => this.change((engine, doc) => engine.rotatePages(doc, indices, angle / 90), turn(angle)),
      undo: () => this.change((engine, doc) => engine.rotatePages(doc, indices, -angle / 90), turn(-angle)),
      page,
      undoPage: page,
    });
  }

  /** Página en blanco detrás de `after`, del tamaño con que se ve esta. */
  insertBlank(after: number): Promise<number> {
    const key = formatKey({ uid: this.takeUid(), rotation: 0, revision: 0 });
    const [width, height] = this.canvas.sizes[after];
    return this.record({
      redo: () => this.change((engine, doc) => engine.insertBlankPage(doc, after + 1, width, height), inserting(after + 1, key)),
      undo: () => this.change((engine, doc) => engine.removePage(doc, after + 1), removing(after + 1)),
      page: after + 1,
      undoPage: after,
    });
  }

  /** Copia de `index` (con sus anotaciones y el texto del OCR) justo detrás. */
  duplicate(index: number): Promise<number> {
    const source = parseKey(this.canvas.keys[index]);
    const uid = this.takeUid();
    const key = formatKey({ uid, rotation: source.rotation, revision: 0 });
    // La copia lleva también el texto del OCR: tampoco va al archivo (document/copy.ts).
    if (this.canvas.ocrPages.has(source.uid)) this.canvas.ocrPages.add(uid);
    return this.record({
      redo: () => this.change((engine, doc) => engine.duplicatePage(doc, index, index + 1), inserting(index + 1, key)),
      undo: () => this.change((engine, doc) => engine.removePage(doc, index + 1), removing(index + 1)),
      page: index + 1,
      undoPage: index,
    });
  }

  /** Borra `index`; se guarda una copia (con sus anotaciones) para poder devolverla. */
  async remove(index: number): Promise<number> {
    const engine = await structure();
    const stash = await engine.stashPage(this.canvas.shownDocument(), index);
    const key = this.canvas.keys[index];
    const dispose = () => void engine.dropStash(stash);
    try {
      return await this.record({
        redo: () => this.change((e, doc) => e.removePage(doc, index), removing(index)),
        undo: () => this.change((e, doc) => e.restorePages(doc, stash, index), inserting(index, key)),
        page: Math.max(0, index - 1),
        undoPage: index,
        dispose,
      });
    } catch (err) {
      dispose();
      throw err;
    }
  }

  /** Lleva la página `from` a la posición final `to`. */
  move(from: number, to: number): Promise<number> {
    return this.record({
      redo: () => this.change((engine, doc) => engine.movePage(doc, from, to), moving(from, to)),
      undo: () => this.change((engine, doc) => engine.movePage(doc, to, from), moving(to, from)),
      page: to,
      undoPage: from,
    });
  }

  /**
   * El motor cambió el contenido de `indices` (la censura, que no se deshace): se muestran con la
   * revisión una más, así su clave cambia y nada reutiliza su imagen ni su texto anteriores.
   */
  async contentChanged(indices: number[]): Promise<void> {
    await this.change((engine, doc) => engine.pageList(doc), revising(indices));
  }

  /** Las claves que tendrán las páginas tras `contentChanged(indices)`. */
  revisedKeys(indices: number[]): string[] {
    return revising(indices)(this.canvas.keys);
  }

  /** Deshace la última operación; devuelve la página a la que ir (null si no había). */
  async undo(): Promise<number | null> {
    const step = this.done.pop();
    if (!step) return null;
    await step.undo();
    this.undone.push(step);
    return step.undoPage;
  }

  async redo(): Promise<number | null> {
    const step = this.undone.pop();
    if (!step) return null;
    await step.redo();
    this.done.push(step);
    return step.page;
  }

  /** Marcadores del documento tal como está ahora (cambian de página al mover las páginas). */
  async toc(): Promise<TocEntry[]> {
    const engine = (await registry()).getEngine();
    const { bookmarks } = await engine.getBookmarks(this.canvas.shownDocument()).toPromise();
    return flattenBookmarks(bookmarks);
  }

  /** Suelta lo que guardan las operaciones (al cerrar el visor). */
  dispose(): void {
    for (const step of [...this.done, ...this.undone]) step.dispose?.();
    this.done = [];
    this.undone = [];
  }

  // ── Auxiliares ─────────────────────────────────────────────────────────
  private takeUid(): number {
    return this.nextUid++;
  }

  /** Hace `step` y lo apunta para deshacerlo (lo deshecho ya no se puede rehacer). */
  private async record(step: Step): Promise<number> {
    await step.redo();
    for (const old of this.undone) old.dispose?.();
    this.undone = [];
    this.done.push(step);
    for (const old of this.done.splice(0, Math.max(0, this.done.length - UNDO_LIMIT))) old.dispose?.();
    return step.page;
  }

  /** Cambia el documento en el motor y lo muestra; `keys` da las claves nuevas a partir de las de ahora. */
  private async change(fn: EngineChange, keys: (current: string[]) => string[]): Promise<void> {
    const pages = await fn(await structure(), this.canvas.shownDocument());
    this.canvas.showPages(pages, keys(this.canvas.keys));
  }
}

// ── Claves tras cada operación ──────────────────────────────────────────────
const inserting = (at: number, key: string) => (keys: string[]) => [...keys.slice(0, at), key, ...keys.slice(at)];
const removing = (at: number) => (keys: string[]) => keys.filter((_, i) => i !== at);
const revising = (indices: number[]) => (keys: string[]) => keys.map((key, i) => {
  if (!indices.includes(i)) return key;
  const parsed = parseKey(key);
  return formatKey({ ...parsed, revision: parsed.revision + 1 });
});
const moving = (from: number, to: number) => (keys: string[]) => {
  const next = keys.filter((_, i) => i !== from);
  next.splice(to, 0, keys[from]);
  return next;
};

/** Marcadores en árbol → lista plana con su nivel (desde 1), como los da Python. */
function flattenBookmarks(bookmarks: PdfBookmarkObject[], level = 1): TocEntry[] {
  return bookmarks.flatMap((bookmark) => [
    { level, title: bookmark.title ?? '', page: targetPage(bookmark) },
    ...flattenBookmarks(bookmark.children ?? [], level + 1),
  ]);
}

function targetPage({ target }: PdfBookmarkObject): number {
  if (target?.type === 'destination') return target.destination.pageIndex;
  if (target?.type === 'action' && 'destination' in target.action) return target.action.destination.pageIndex;
  return 0;
}
