// Operaciones sobre el documento del visor: guardar, rotar, insertar, duplicar,
// eliminar, mover y exportar (equivale a _page_ops_mixin.py y _file_ops_mixin.py en
// Qt). Cada operación del backend devuelve la información actualizada del
// documento; aquí se decide a qué página ir después, como hace Qt.
//
// Las anotaciones las edita EmbedPDF: antes de cada operación que necesita el documento al
// día en Python (guardar, cambiar páginas, censurar, exportar una página) se le pasan (`sync`).
import { call } from '$lib/api.js';
import { fileName } from '$lib/dom.js';
import { askChoice, confirmDialog, progressDialog, setStatus, toast } from '$lib/ui.js';

export class DocumentActions {
  /**
   * @param {object} info resultado de `viewer.open`
   * @param {{ page: () => number, sync: () => Promise, apply: (info, page) => void }} view
   *   `page()`: página actual; `sync()`: pasar las anotaciones a Python; `apply(info, page)`:
   *   mostrar el documento actualizado e ir a `page`.
   */
  constructor(info, view) {
    this.info = info;
    this.view = view;
    this.queue = Promise.resolve(); // las operaciones se encadenan: cada una ve el resultado de la anterior
  }

  get modified() {
    return this.info.modified;
  }

  get pageCount() {
    return this.info.pages.length;
  }

  // ── Páginas ────────────────────────────────────────────────────────────
  rotate(angle, allPages = false) {
    return this._change(async (page) => [await call('viewer.rotate', this.info.id, angle, allPages ? null : page), page]);
  }

  insertBlank() {
    return this._change(async (page) => [await call('viewer.insert_blank', this.info.id, page), page + 1]);
  }

  duplicate() {
    return this._change(async (page) => [await call('viewer.duplicate', this.info.id, page), page + 1]);
  }

  remove() {
    return this._change(async (page) => {
      if (this.pageCount <= 1) {
        toast('No se puede eliminar la única página del documento.', 'warning');
        return null;
      }
      if (!(await confirmDialog('Eliminar Página', `¿Estás seguro de eliminar la página ${page + 1}?`))) return null;
      return [await call('viewer.delete_page', this.info.id, page), Math.max(0, page - 1)];
    });
  }

  /** Mueve la página `src` a la posición final `dst` (por defecto, desde la actual). */
  move(dst, src = null) {
    return this._change(async (page) => {
      const from = src ?? page;
      if (from === dst || dst < 0 || dst >= this.pageCount) return null;
      return [await call('viewer.move_page', this.info.id, from, dst), dst];
    });
  }

  /** Deshace la última operación de página (girar, insertar, duplicar, borrar, mover). */
  undoPages() {
    return this._change(async (page) => {
      const { info, page: target } = await call('viewer.undo_pages', this.info.id);
      return [info, target ?? page];
    });
  }

  redoPages() {
    return this._change(async (page) => {
      const { info, page: target } = await call('viewer.redo_pages', this.info.id);
      return [info, target ?? page];
    });
  }

  get canUndoPages() {
    return Boolean(this.info.page_undo);
  }

  get canRedoPages() {
    return Boolean(this.info.page_redo);
  }

  /** Detecta la orientación de la página actual (escaneo o texto girado) y la corrige. */
  fixOrientation() {
    return this._change(async (page) => {
      const { angle, info } = await call('ocr.orientation', this.info.id, page);
      if (!info) {
        toast('La página ya se encuentra en la orientación adecuada (0°).', 'info');
        return null;
      }
      toast(`Se detectó una desviación de ${angle}° y la página fue reorientada.`, 'success');
      return [info, page];
    });
  }

  /** Corrige la orientación de todas las páginas, con progreso y «Cancelar». */
  fixOrientationAll() {
    return this._change(async (page) => {
      const total = this.pageCount;
      const progress = progressDialog('Corregir orientación', 'Analizando orientación de páginas…');
      let last = null;
      let corrected = 0;
      try {
        for (let index = 0; index < total && !progress.cancelled; index++) {
          progress.update(index, total, `Analizando orientación de páginas… (${index + 1} de ${total})`);
          const { info } = await call('ocr.orientation', this.info.id, index);
          if (info) {
            last = info;
            corrected++;
          }
        }
      } finally {
        progress.close();
      }
      setStatus(corrected
        ? `Se corrigió la orientación en ${corrected} página(s)`
        : 'Todas las páginas ya tenían la orientación adecuada');
      return last && [last, page];
    });
  }

  /** Ejecuta `fn(página)` → [info, página destino] | null en la cola del documento (p. ej. la censura). */
  change(fn) {
    return this._change(fn);
  }

  /** Ejecuta `fn(página)` → [info, página destino] | null, en orden y avisando de los errores. */
  _change(fn) {
    const task = this.queue.then(async () => {
      try {
        await this.view.sync();
        const result = await fn(this.view.page());
        if (result) this._apply(...result);
      } catch (err) {
        toast(err.message, 'danger');
      }
    });
    this.queue = task;
    return task;
  }

  _apply(info, page) {
    this.info = info;
    this.view.apply(info, Math.min(page, info.pages.length - 1));
  }

  // ── Guardar ────────────────────────────────────────────────────────────
  /** Guarda sobre el original (Ctrl+S). Resuelve true si se guardó. */
  save() {
    return this._file(async () => {
      await this.view.sync();
      try {
        return this._saved(await call('viewer.save', this.info.id));
      } catch (err) {
        // Sin permiso de escritura, o con censura aplicada (nunca se sobrescribe el original).
        if (err.code !== 'permission_denied' && err.code !== 'redacted') throw err;
        toast(err.message, err.code === 'redacted' ? 'info' : 'warning');
        return this._saveAs();
      }
    });
  }

  /** Guarda una copia en otra ruta (Ctrl+Shift+S); la pestaña pasa a ser ese archivo. */
  saveAs() {
    return this._file(async () => {
      await this.view.sync();
      return this._saveAs();
    });
  }

  async _saveAs() {
    const info = await call('viewer.save_as', this.info.id);
    return info ? this._saved(info) : false;
  }

  _saved(info) {
    this._apply(info, this.view.page());
    setStatus(`Guardado: ${info.name}`);
    return true;
  }

  /** Ejecuta `fn` en la cola del documento (p. ej. pasar las anotaciones), avisando de los errores. */
  run(fn) {
    return this._file(fn);
  }

  /** Cambiaron las anotaciones: Python lo apunta (aviso de cambios sin guardar al cerrar). */
  annotationsChanged() {
    if (this.info.modified) return Promise.resolve();
    this.info = { ...this.info, modified: true }; // no se vuelve a avisar hasta guardar
    return this._file(async () => {
      this.info = { ...this.info, ...(await call('viewer.annotations_changed', this.info.id)) };
    });
  }

  /** Como `_change`, pero resuelve el valor de `fn` (false si falla). */
  _file(fn) {
    const task = this.queue.then(async () => {
      try {
        return await fn();
      } catch (err) {
        toast(err.message, 'danger');
        return false;
      }
    });
    this.queue = task.then(() => {});
    return task;
  }

  /** Pregunta por los cambios sin guardar antes de cerrar la pestaña. True si puede cerrarse. */
  async canClose() {
    await this.queue;
    if (!this.modified) return true;
    // Con censura aplicada solo se guarda como copia, para conservar el original (como Qt).
    const redacted = Boolean(this.info.redacted);
    const message = redacted
      ? `«${this.info.name}» tiene censura aplicada.\n\nSolo se puede guardar como copia para preservar el original.`
      : `«${this.info.name}» tiene cambios sin guardar.\n\n¿Qué deseas hacer?`;
    const choice = await askChoice('Cambios sin guardar', message, [
      { label: 'Cancelar', value: null },
      { label: 'Cerrar sin guardar', value: 'discard', tone: 'danger' },
      { label: redacted ? 'Guardar como… y cerrar' : 'Guardar y cerrar', value: 'save', tone: 'primary' },
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
      const path = await call('viewer.extract_page', this.info.id, page);
      if (path) setStatus(`Página ${page + 1} extraída en ${fileName(path)}`);
    });
  }

  exportText() {
    return this._file(async () => {
      const path = await call('viewer.export_text', this.info.id);
      if (path) setStatus(`Texto exportado en ${fileName(path)}`);
    });
  }

  exportImages() {
    return this._file(async () => {
      const result = await call('viewer.export_images', this.info.id);
      if (!result) return;
      if (result.count) setStatus(`Se extrajeron ${result.count} imágenes en ${result.folder}`);
      else toast('No se encontraron imágenes incrustadas en el documento.', 'info');
    });
  }

  // ── Menú ⋮ (mismo orden que _build_more_menu en Qt) ────────────────────
  menuItems() {
    const page = this.view.page();
    return [
      { label: 'Guardar cambios (Ctrl+S)', icon: 'save', onSelect: () => this.save() },
      { label: 'Guardar PDF como… (Ctrl+Shift+S)', icon: 'save', onSelect: () => this.saveAs() },
      'separator',
      { label: 'Rotar 90° a la derecha (esta página)', icon: 'rotate-cw', onSelect: () => this.rotate(90) },
      { label: 'Rotar 90° a la izquierda (esta página)', icon: 'rotate-ccw', onSelect: () => this.rotate(-90) },
      { label: 'Voltear 180° (esta página)', icon: 'rotate-cw', onSelect: () => this.rotate(180) },
      { label: 'Voltear 180° (todas las páginas)', icon: 'rotate-cw', onSelect: () => this.rotate(180, true) },
      { label: 'Corregir orientación del escaneo (esta página)', icon: 'compass', onSelect: () => this.fixOrientation() },
      { label: 'Corregir orientación (todas las páginas)', icon: 'compass', onSelect: () => this.fixOrientationAll() },
      'separator',
      { label: 'Insertar página en blanco', icon: 'file-plus', onSelect: () => this.insertBlank() },
      { label: 'Duplicar página actual', icon: 'copy', onSelect: () => this.duplicate() },
      { label: 'Eliminar página actual', icon: 'trash', onSelect: () => this.remove() },
      'separator',
      { label: 'Mover página arriba', icon: 'arrow-up', disabled: page <= 0, onSelect: () => this.move(page - 1) },
      { label: 'Mover página abajo', icon: 'arrow-down', disabled: page >= this.pageCount - 1, onSelect: () => this.move(page + 1) },
      'separator',
      { label: 'Extraer página actual a nuevo PDF...', icon: 'files', onSelect: () => this.extractPage() },
      { label: 'Exportar texto del documento (.txt)...', icon: 'file-text', onSelect: () => this.exportText() },
      { label: 'Extraer todas las imágenes del documento...', icon: 'image', onSelect: () => this.exportImages() },
    ];
  }
}
