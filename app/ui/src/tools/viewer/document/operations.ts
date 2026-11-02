// Operaciones sobre el documento del visor: guardar, rotar, insertar, duplicar,
// eliminar, mover y exportar (equivale a _page_ops_mixin.py y _file_ops_mixin.py en
// Qt). Cada operación del backend devuelve la información actualizada del
// documento; aquí se decide a qué página ir después, como hace Qt.
//
// Las anotaciones las edita EmbedPDF: antes de cada operación que necesita el documento al
// día en Python (guardar, cambiar páginas, censurar, exportar una página) se le pasan (`sync`).
import { call, type ApiError } from '$lib/api.ts';
import { fileName } from '$lib/dom.ts';
import type { MenuItem } from '$lib/menu.svelte.ts';
import type { DocumentInfo } from '$lib/types.ts';
import { askChoice, confirmDialog, progressDialog, setStatus, toast } from '$lib/ui.ts';
import { t, tip } from '$texts';

const T = t.viewer.document;

/** Lo que necesitan las operaciones del visor (Viewer.svelte). */
export interface DocumentView {
  /** Página actual. */
  page(): number;
  /** Pasa las anotaciones a Python. */
  sync(): Promise<unknown>;
  /** Muestra el documento actualizado e ir a `page`. */
  apply(info: DocumentInfo, page: number): void;
}

/** Cambio del documento: [info nueva, página a la que ir], o null si no se hizo nada. */
export type Change = [DocumentInfo, number] | null;

/** Resultado de las operaciones de deshacer y rehacer páginas. */
interface PagesUndo {
  info: DocumentInfo;
  page: number | null;
}

export class DocumentActions {
  info: DocumentInfo;
  view: DocumentView;
  queue: Promise<unknown> = Promise.resolve(); // las operaciones se encadenan: cada una ve el resultado de la anterior

  constructor(info: DocumentInfo, view: DocumentView) {
    this.info = info;
    this.view = view;
  }

  get modified(): boolean {
    return this.info.modified;
  }

  get pageCount(): number {
    return this.info.pages.length;
  }

  // ── Páginas ────────────────────────────────────────────────────────────
  rotate(angle: number, allPages = false) {
    return this._change(async (page) => [
      await call<DocumentInfo>('viewer.rotate', this.info.id, angle, allPages ? null : page), page,
    ]);
  }

  insertBlank() {
    return this._change(async (page) => [await call<DocumentInfo>('viewer.insert_blank', this.info.id, page), page + 1]);
  }

  duplicate() {
    return this._change(async (page) => [await call<DocumentInfo>('viewer.duplicate', this.info.id, page), page + 1]);
  }

  remove() {
    return this._change(async (page) => {
      if (this.pageCount <= 1) {
        toast(T.onlyPage, 'warning');
        return null;
      }
      if (!(await confirmDialog(T.removeTitle, T.removeQuestion(page + 1)))) return null;
      return [await call<DocumentInfo>('viewer.delete_page', this.info.id, page), Math.max(0, page - 1)];
    });
  }

  /** Mueve la página `src` a la posición final `dst` (por defecto, desde la actual). */
  move(dst: number, src: number | null = null) {
    return this._change(async (page) => {
      const from = src ?? page;
      if (from === dst || dst < 0 || dst >= this.pageCount) return null;
      return [await call<DocumentInfo>('viewer.move_page', this.info.id, from, dst), dst];
    });
  }

  /** Deshace la última operación de página (girar, insertar, duplicar, borrar, mover). */
  undoPages() {
    return this._change(async (page) => {
      const { info, page: target } = await call<PagesUndo>('viewer.undo_pages', this.info.id);
      return [info, target ?? page];
    });
  }

  redoPages() {
    return this._change(async (page) => {
      const { info, page: target } = await call<PagesUndo>('viewer.redo_pages', this.info.id);
      return [info, target ?? page];
    });
  }

  get canUndoPages(): boolean {
    return Boolean(this.info.page_undo);
  }

  get canRedoPages(): boolean {
    return Boolean(this.info.page_redo);
  }

  /** Detecta la orientación de la página actual (escaneo o texto girado) y la corrige. */
  fixOrientation() {
    return this._change(async (page) => {
      const { angle, info } = await call<{ angle: number; info: DocumentInfo | null }>('ocr.orientation', this.info.id, page);
      if (!info) {
        toast(T.orientationOk, 'info');
        return null;
      }
      toast(T.orientationFixed(angle), 'success');
      return [info, page];
    });
  }

  /** Corrige la orientación de todas las páginas, con progreso y «Cancelar». */
  fixOrientationAll() {
    return this._change(async (page) => {
      const total = this.pageCount;
      const progress = progressDialog(T.orientationTitle, T.orientationAnalyzing);
      let last: DocumentInfo | null = null;
      let corrected = 0;
      try {
        for (let index = 0; index < total && !progress.cancelled; index++) {
          progress.update(index, total, T.orientationProgress(index + 1, total));
          const { info } = await call<{ info: DocumentInfo | null }>('ocr.orientation', this.info.id, index);
          if (info) {
            last = info;
            corrected++;
          }
        }
      } finally {
        progress.close();
      }
      setStatus(corrected ? T.orientationDone(corrected) : T.orientationNone);
      return last && [last, page];
    });
  }

  /** Ejecuta `fn(página)` → [info, página destino] | null en la cola del documento (p. ej. la censura). */
  change(fn: (page: number) => Promise<Change>) {
    return this._change(fn);
  }

  /** Ejecuta `fn(página)` → [info, página destino] | null, en orden y avisando de los errores. */
  _change(fn: (page: number) => Promise<Change>): Promise<void> {
    const task = this.queue.then(async () => {
      try {
        await this.view.sync();
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
    this.info = info;
    this.view.apply(info, Math.min(page, info.pages.length - 1));
  }

  // ── Guardar ────────────────────────────────────────────────────────────
  /** Guarda sobre el original (Ctrl+S). Resuelve true si se guardó. */
  save(): Promise<boolean> {
    return this._file(async () => {
      await this.view.sync();
      try {
        return this._saved(await call<DocumentInfo>('viewer.save', this.info.id));
      } catch (err) {
        // Sin permiso de escritura, o con censura aplicada (nunca se sobrescribe el original).
        const { code, message } = err as ApiError;
        if (code !== 'permission_denied' && code !== 'redacted') throw err;
        toast(message, code === 'redacted' ? 'info' : 'warning');
        return this._saveAs();
      }
    });
  }

  /** Guarda una copia en otra ruta (Ctrl+Shift+S); la pestaña pasa a ser ese archivo. */
  saveAs(): Promise<boolean> {
    return this._file(async () => {
      await this.view.sync();
      return this._saveAs();
    });
  }

  async _saveAs(): Promise<boolean> {
    const info = await call<DocumentInfo | null>('viewer.save_as', this.info.id);
    return info ? this._saved(info) : false;
  }

  _saved(info: DocumentInfo): boolean {
    this._apply(info, this.view.page());
    setStatus(T.saved(info.name));
    return true;
  }

  /** Ejecuta `fn` en la cola del documento (p. ej. pasar las anotaciones), avisando de los errores. */
  run<R>(fn: () => Promise<R>): Promise<R | false> {
    return this._file(fn);
  }

  /** Cambiaron las anotaciones: Python lo apunta (aviso de cambios sin guardar al cerrar). */
  annotationsChanged(): Promise<unknown> {
    if (this.info.modified) return Promise.resolve();
    this.info = { ...this.info, modified: true }; // no se vuelve a avisar hasta guardar
    return this._file(async () => {
      this.info = { ...this.info, ...(await call<Partial<DocumentInfo>>('viewer.annotations_changed', this.info.id)) };
    });
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
  extractPage() {
    return this._file(async () => {
      await this.view.sync(); // la página extraída lleva sus anotaciones
      const page = this.view.page();
      const path = await call<string | null>('viewer.extract_page', this.info.id, page);
      if (path) setStatus(T.pageExtracted(page + 1, fileName(path)));
    });
  }

  exportText() {
    return this._file(async () => {
      const path = await call<string | null>('viewer.export_text', this.info.id);
      if (path) setStatus(T.textExported(fileName(path)));
    });
  }

  exportImages() {
    return this._file(async () => {
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
