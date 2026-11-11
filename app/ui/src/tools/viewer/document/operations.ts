// Operaciones sobre el documento del visor: guardar, rotar, insertar, duplicar,
// eliminar, mover y exportar (equivale a _page_ops_mixin.py y _file_ops_mixin.py en
// Qt). Aquí se decide a qué página ir después de cada una, como hace Qt.
//
// El documento es de EmbedPDF: las operaciones de página las hace su motor en el documento abierto
// (pages.ts), y al guardar o extraer una página Python escribe tal cual la copia que saca el motor
// (copy.ts). Lo demás lo hace Python con el documento al día: antes se le pasa la copia (`sync`).
import { call, type ApiError } from '$lib/api.ts';
import { fileName } from '$lib/dom.ts';
import type { MenuItem } from '$lib/menu.svelte.ts';
import type { DocumentInfo } from '$lib/types.ts';
import { askChoice, confirmDialog, progressDialog, setStatus, toast } from '$lib/ui.ts';
import { t, tip } from '$texts';
import type { PageRecognizer } from '../ocr/recognize.ts';
import { send, type DocumentCopy } from './copy.ts';
import type { PageEditor } from './pages.ts';

const T = t.viewer.document;

/** Lo que necesitan las operaciones del visor (Viewer.svelte). */
export interface DocumentView {
  /** Página actual. */
  page(): number;
  /** Escribe en el documento de EmbedPDF las anotaciones pendientes (antes de cambiar páginas). */
  commit(): Promise<void>;
  /** Muestra el documento actualizado e ir a `page`. */
  apply(info: DocumentInfo, page: number): void;
}

/** Cambio del documento: [info nueva, página a la que ir], o null si no se hizo nada. */
export type Change = [DocumentInfo, number] | null;

export class DocumentActions {
  info: DocumentInfo;
  view: DocumentView;
  pages: PageEditor;
  copy: DocumentCopy;
  recognizer: PageRecognizer;
  queue: Promise<unknown> = Promise.resolve(); // las operaciones se encadenan: cada una ve el resultado de la anterior

  constructor(info: DocumentInfo, view: DocumentView, pages: PageEditor, copy: DocumentCopy, recognizer: PageRecognizer) {
    this.view = view;
    this.pages = pages;
    this.copy = copy;
    this.recognizer = recognizer;
    this.info = this._withState(info);
  }

  get modified(): boolean {
    return this.info.modified;
  }

  get pageCount(): number {
    return this.info.pages.length;
  }

  // ── Páginas ────────────────────────────────────────────────────────────
  rotate(angle: number, allPages = false) {
    return this._pages((page) => {
      const indices = allPages ? this.info.pages.map((_, i) => i) : [page];
      return this.pages.rotate(indices, angle, page);
    });
  }

  insertBlank() {
    return this._pages((page) => this.pages.insertBlank(page));
  }

  duplicate() {
    return this._pages((page) => this.pages.duplicate(page));
  }

  remove() {
    return this._pages(async (page) => {
      if (this.pageCount <= 1) {
        toast(T.onlyPage, 'warning');
        return null;
      }
      if (!(await confirmDialog(T.removeTitle, T.removeQuestion(page + 1)))) return null;
      return this.pages.remove(page);
    });
  }

  /** Mueve la página `src` a la posición final `dst` (por defecto, desde la actual). */
  move(dst: number, src: number | null = null) {
    return this._pages(async (page) => {
      const from = src ?? page;
      if (from === dst || dst < 0 || dst >= this.pageCount) return null;
      return this.pages.move(from, dst);
    });
  }

  /** Deshace la última operación de página (girar, insertar, duplicar, borrar, mover). */
  undoPages() {
    return this._pages(() => this.pages.undo());
  }

  redoPages() {
    return this._pages(() => this.pages.redo());
  }

  get canUndoPages(): boolean {
    return this.pages.canUndo;
  }

  get canRedoPages(): boolean {
    return this.pages.canRedo;
  }

  /** Detecta la orientación de la página actual (escaneo o texto girado) y la corrige. */
  fixOrientation() {
    return this._pages(async (page) => {
      const angle = await this.recognizer.orientation(page);
      if (!angle) {
        toast(T.orientationOk, 'info');
        return null;
      }
      toast(T.orientationFixed(angle), 'success');
      return this.pages.rotate([page], angle, page);
    });
  }

  /** Corrige la orientación de todas las páginas, con progreso y «Cancelar». */
  fixOrientationAll() {
    return this._pages(async (page) => {
      const total = this.pageCount;
      const progress = progressDialog(T.orientationTitle, T.orientationAnalyzing);
      const turns: [number, number][] = []; // [página, ángulo]
      try {
        for (let index = 0; index < total && !progress.cancelled; index++) {
          progress.update(index, total, T.orientationProgress(index + 1, total));
          const angle = await this.recognizer.orientation(index);
          if (angle) turns.push([index, angle]);
        }
      } finally {
        progress.close();
      }
      // Cada giro se deshace por separado, como si se hubiera hecho a mano.
      for (const [index, angle] of turns) await this.pages.rotate([index], angle, page);
      setStatus(turns.length ? T.orientationDone(turns.length) : T.orientationNone);
      return turns.length ? page : null;
    });
  }

  /**
   * Ejecuta en la cola del documento `fn(página)`, que cambia las páginas con el editor y
   * devuelve a cuál ir (null si no hizo nada), y muestra el resultado.
   */
  _pages(fn: (page: number) => Promise<number | null>): Promise<void> {
    const task = this.queue.then(async () => {
      try {
        await this.view.commit(); // las anotaciones van con su página
        const target = await fn(this.view.page());
        if (target === null) return;
        this.copy.changed(); // Python recibe las páginas nuevas en el próximo `sync`
        const info = { ...this.info, pages: this.pages.sizes, keys: this.pages.keys, toc: await this.pages.toc() };
        this._apply(info, target);
      } catch (err) {
        toast((err as Error).message, 'danger');
      }
    });
    this.queue = task;
    return task;
  }

  /** Ejecuta `fn(página)` → [info, página destino] | null en la cola del documento (p. ej. la censura). */
  change(fn: (page: number) => Promise<Change>) {
    return this._change(fn);
  }

  /** Ejecuta `fn(página)` → [info, página destino] | null, en orden y avisando de los errores. */
  _change(fn: (page: number) => Promise<Change>): Promise<void> {
    const task = this.queue.then(async () => {
      try {
        await this.copy.sync();
        const result = await fn(this.view.page());
        if (result) this._apply(...result);
      } catch (err) {
        toast((err as Error).message, 'danger');
      }
    });
    this.queue = task;
    return task;
  }

  _apply(info: DocumentInfo, page: number): void {
    this.info = this._withState(info);
    this.view.apply(this.info, Math.min(page, info.pages.length - 1));
  }

  /**
   * `info` con «cambios sin guardar» al día: anotaciones o censura (lo dice Python) o una
   * estructura de páginas distinta de la guardada (la lleva el editor).
   */
  _withState(info: DocumentInfo): DocumentInfo {
    return { ...info, modified: info.annotated || info.redacted || this.pages.changedWith(info.keys) };
  }

  // ── Guardar ────────────────────────────────────────────────────────────
  /** Guarda sobre el original (Ctrl+S). Resuelve true si se guardó. */
  save(): Promise<boolean> {
    return this._file(async () => {
      try {
        return await this._write('viewer.save');
      } catch (err) {
        // Sin permiso de escritura, o con censura aplicada (nunca se sobrescribe el original).
        const { code, message } = err as ApiError;
        if (code !== 'permission_denied' && code !== 'redacted') throw err;
        toast(message, code === 'redacted' ? 'info' : 'warning');
        return this._write('viewer.save_as');
      }
    });
  }

  /** Guarda una copia en otra ruta (Ctrl+Shift+S); la pestaña pasa a ser ese archivo. */
  saveAs(): Promise<boolean> {
    return this._file(() => this._write('viewer.save_as'));
  }

  /**
   * Sube la copia del documento y Python la escribe en el archivo con `method`; también pasa a
   * ser su documento. Resuelve false si se canceló el diálogo de «Guardar como».
   */
  async _write(method: 'viewer.save' | 'viewer.save_as'): Promise<boolean> {
    const copy = await this.copy.upload();
    const info = await call<DocumentInfo | null>(method, this.info.id, copy.url, copy.uids);
    if (!info) return false;
    copy.adopted();
    this.pages.markSaved();
    this._apply(info, this.view.page());
    setStatus(T.saved(info.name));
    return true;
  }

  /** Ejecuta `fn` en la cola del documento (p. ej. pasar el documento a Python), avisando de los errores. */
  run<R>(fn: () => Promise<R>): Promise<R | false> {
    return this._file(fn);
  }

  /** Cambiaron las anotaciones: Python lo apunta (aviso de cambios sin guardar al cerrar). */
  annotationsChanged(): Promise<unknown> {
    if (this.info.annotated) return Promise.resolve(); // no se vuelve a avisar hasta guardar
    this.info = this._withState({ ...this.info, annotated: true });
    return this._file(() => call('viewer.annotations_changed', this.info.id));
  }

  /** Como `_change`, pero resuelve el valor de `fn` (false si falla). */
  _file<R>(fn: () => Promise<R>): Promise<R | false> {
    const task = this.queue.then(async () => {
      try {
        return await fn();
      } catch (err) {
        toast((err as Error).message, 'danger');
        return false as const;
      }
    });
    this.queue = task.then(() => {});
    return task;
  }

  /** Pregunta por los cambios sin guardar antes de cerrar la pestaña. True si puede cerrarse. */
  async canClose(): Promise<boolean> {
    await this.queue;
    if (!this.modified) return true;
    // Con censura aplicada solo se guarda como copia, para conservar el original (como Qt).
    const redacted = Boolean(this.info.redacted);
    const message = redacted ? T.unsavedRedacted(this.info.name) : T.unsavedQuestion(this.info.name);
    const choice = await askChoice<'discard' | 'save' | null>(T.unsavedTitle, message, [
      { label: T.cancel, value: null },
      { label: T.discard, value: 'discard', tone: 'danger' },
      { label: redacted ? T.saveAsClose : T.saveClose, value: 'save', tone: 'primary' },
    ]);
    if (choice === 'discard') return true;
    if (choice !== 'save') return false;
    return redacted ? this.saveAs() : this.save();
  }

  // ── Exportar ───────────────────────────────────────────────────────────
  /** Guarda la página actual (con sus anotaciones) como un PDF nuevo: lo saca el motor y Python lo escribe. */
  extractPage() {
    return this._file(async () => {
      const page = this.view.page();
      const url = await send(await this.copy.page(page));
      const path = await call<string | null>('viewer.extract_page', this.info.id, page, url);
      if (path) setStatus(T.pageExtracted(page + 1, fileName(path)));
    });
  }

  exportText() {
    return this._file(async () => {
      await this.copy.sync(); // las páginas como están ahora
      const path = await call<string | null>('viewer.export_text', this.info.id);
      if (path) setStatus(T.textExported(fileName(path)));
    });
  }

  exportImages() {
    return this._file(async () => {
      await this.copy.sync();
      const result = await call<{ folder: string; count: number } | null>('viewer.export_images', this.info.id);
      if (!result) return;
      if (result.count) setStatus(T.imagesExported(result.count, result.folder));
      else toast(T.noImages, 'info');
    });
  }

  // ── Menú ⋮ (mismo orden que _build_more_menu en Qt) ────────────────────
  menuItems(): MenuItem[] {
    const M = T.menu;
    const page = this.view.page();
    return [
      { label: tip(M.save), icon: 'save', onSelect: () => this.save() },
      { label: tip(M.saveAs), icon: 'save', onSelect: () => this.saveAs() },
      'separator',
      { label: M.rotateRight, icon: 'rotate-cw', onSelect: () => this.rotate(90) },
      { label: M.rotateLeft, icon: 'rotate-ccw', onSelect: () => this.rotate(-90) },
      { label: M.flip, icon: 'rotate-cw', onSelect: () => this.rotate(180) },
      { label: M.flipAll, icon: 'rotate-cw', onSelect: () => this.rotate(180, true) },
      { label: M.fixOrientation, icon: 'compass', onSelect: () => this.fixOrientation() },
      { label: M.fixOrientationAll, icon: 'compass', onSelect: () => this.fixOrientationAll() },
      'separator',
      { label: M.insertBlank, icon: 'file-plus', onSelect: () => this.insertBlank() },
      { label: M.duplicate, icon: 'copy', onSelect: () => this.duplicate() },
      { label: M.remove, icon: 'trash', onSelect: () => this.remove() },
      'separator',
      { label: M.moveUp, icon: 'arrow-up', disabled: page <= 0, onSelect: () => this.move(page - 1) },
      { label: M.moveDown, icon: 'arrow-down', disabled: page >= this.pageCount - 1, onSelect: () => this.move(page + 1) },
      'separator',
      { label: M.extractPage, icon: 'files', onSelect: () => this.extractPage() },
      { label: M.exportText, icon: 'file-text', onSelect: () => this.exportText() },
      { label: M.exportImages, icon: 'image', onSelect: () => this.exportImages() },
    ];
  }
}
