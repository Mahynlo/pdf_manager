// El motor PDFium de EmbedPDF con lo que le falta para ser el dueño del documento del visor:
// cambiar sus páginas sin volver a abrirlo. Corre en el worker (worker.ts); lo prueba también
// Python con el motor real (tests/engine_task.mjs), por eso no depende de nada de la app.
//
// Usa partes privadas de PdfiumNative 2.15.1 (`Internals`): revisarlas al actualizar EmbedPDF.
import { PdfiumNative } from '@embedpdf/engines/pdfium';
import type { PdfDocumentObject, PdfPageObject } from '@embedpdf/models';

/** Lo privado de PdfiumNative que se usa aquí. */
interface Internals {
  cache: { getContext(id: string): DocumentContext | undefined };
  pdfiumModule: Pdfium;
  memoryManager: { malloc(size: number): number; free(ptr: number): void };
  withWString<T>(value: string, fn: (ptr: number) => T): T;
}

interface DocumentContext {
  docPtr: number;
  normalizeRotation: boolean;
  pageCache: { forceReleaseAll(): void };
  borrowPage<T>(index: number, fn: (page: { pagePtr: number }) => T): T;
}

/** Las funciones de PDFium que se llaman directamente (todas existen en el wasm de EmbedPDF). */
interface Pdfium {
  pdfium: { getValue(ptr: number, type: string): number; setValue(ptr: number, value: number, type: string): void };
  FPDF_GetPageCount(doc: number): number;
  FPDF_GetPageSizeByIndexF(doc: number, index: number, size: number): boolean;
  EPDF_GetPageSizeByIndexNormalized(doc: number, index: number, size: number): boolean;
  EPDF_GetPageRotationByIndex(doc: number, index: number): number;
  EPDFDoc_GetPageObjectNumberByIndex(doc: number, index: number): number;
  FPDFPage_SetRotation(page: number, rotation: number): void;
  FPDF_MovePages(doc: number, indices: number, count: number, dest: number): boolean;
  FPDFPage_Delete(doc: number, index: number): void;
  FPDFPage_New(doc: number, index: number, width: number, height: number): number;
  FPDF_ClosePage(page: number): void;
  FPDF_ImportPagesByIndex(dest: number, src: number, indices: number, count: number, at: number): boolean;
  FPDF_CreateNewDocument(): number;
  FPDF_CloseDocument(doc: number): void;
  FPDFPage_GetAnnotCount(page: number): number;
  FPDFPage_GetAnnot(page: number, index: number): number;
  FPDFPage_CloseAnnot(annot: number): void;
  FPDFAnnot_SetStringValue(annot: number, key: string, value: number): boolean;
}

/**
 * Páginas guardadas aparte para poder devolverlas (deshacer un borrado). No son de un documento:
 * cuando Python cambia el documento (censura), el visor abre otra versión y siguen valiendo. Las
 * suelta quien las guardó (`dropStash`).
 */
interface Stash {
  ptr: number; // documento de PDFium con esas páginas
  count: number;
}

export class AppNative extends PdfiumNative {
  private stashes = new Map<string, Stash>();
  private stashCount = 0;

  private get internals(): Internals {
    return this as unknown as Internals;
  }

  private context(doc: PdfDocumentObject): DocumentContext {
    const ctx = this.internals.cache.getContext(doc.id);
    if (!ctx) throw new Error(`El documento ${doc.id} no está abierto`);
    return ctx;
  }

  /** Antes de cambiar el orden: la caché de páginas va por número de página, que cambia. */
  private forgetPages(ctx: DocumentContext): void {
    ctx.pageCache.forceReleaseAll();
  }

  /** Llama a `fn` con un int[] de PDFium que contiene `values`. */
  private withIndices<T>(values: number[], fn: (ptr: number) => T): T {
    const { memoryManager, pdfiumModule } = this.internals;
    const ptr = memoryManager.malloc(values.length * 4);
    try {
      values.forEach((value, i) => pdfiumModule.pdfium.setValue(ptr + i * 4, value, 'i32'));
      return fn(ptr);
    } finally {
      memoryManager.free(ptr);
    }
  }

  // ── Páginas ────────────────────────────────────────────────────────────
  /** Las páginas del documento, como las da openDocumentBuffer. */
  pageList(doc: PdfDocumentObject): PdfPageObject[] {
    const ctx = this.context(doc);
    const { pdfiumModule: m, memoryManager } = this.internals;
    const size = memoryManager.malloc(8);
    try {
      const pages: PdfPageObject[] = [];
      for (let index = 0; index < m.FPDF_GetPageCount(ctx.docPtr); index++) {
        if (ctx.normalizeRotation) m.EPDF_GetPageSizeByIndexNormalized(ctx.docPtr, index, size);
        else m.FPDF_GetPageSizeByIndexF(ctx.docPtr, index, size);
        pages.push({
          index,
          size: { width: m.pdfium.getValue(size, 'float'), height: m.pdfium.getValue(size + 4, 'float') },
          rotation: m.EPDF_GetPageRotationByIndex(ctx.docPtr, index),
          objectNumber: m.EPDFDoc_GetPageObjectNumberByIndex(ctx.docPtr, index),
        } as PdfPageObject);
      }
      return pages;
    } finally {
      memoryManager.free(size);
    }
  }

  /** Gira `indices` `turns` cuartos de vuelta (negativo: a la izquierda) y lo apunta en el PDF. */
  rotatePages(doc: PdfDocumentObject, indices: number[], turns: number): PdfPageObject[] {
    const ctx = this.context(doc);
    const m = this.internals.pdfiumModule;
    for (const index of indices) {
      // El giro actual, del diccionario de la página: con la rotación normalizada de EmbedPDF,
      // la página cargada dice 0 aunque esté girada.
      const rotation = (((m.EPDF_GetPageRotationByIndex(ctx.docPtr, index) + turns) % 4) + 4) % 4;
      ctx.borrowPage(index, ({ pagePtr }) => m.FPDFPage_SetRotation(pagePtr, rotation));
    }
    return this.pageList(doc);
  }

  /** Lleva la página `from` a la posición final `to`. */
  movePage(doc: PdfDocumentObject, from: number, to: number): PdfPageObject[] {
    const ctx = this.context(doc);
    this.forgetPages(ctx);
    const moved = this.withIndices([from], (ptr) => this.internals.pdfiumModule.FPDF_MovePages(ctx.docPtr, ptr, 1, to));
    if (!moved) throw new Error('No se pudo mover la página');
    return this.pageList(doc);
  }

  removePage(doc: PdfDocumentObject, index: number): PdfPageObject[] {
    const ctx = this.context(doc);
    this.forgetPages(ctx);
    this.internals.pdfiumModule.FPDFPage_Delete(ctx.docPtr, index);
    return this.pageList(doc);
  }

  /** Página en blanco de `width` × `height` puntos en la posición `index`. */
  insertBlankPage(doc: PdfDocumentObject, index: number, width: number, height: number): PdfPageObject[] {
    const ctx = this.context(doc);
    this.forgetPages(ctx);
    const m = this.internals.pdfiumModule;
    const page = m.FPDFPage_New(ctx.docPtr, index, width, height);
    if (!page) throw new Error('No se pudo insertar la página');
    m.FPDF_ClosePage(page);
    return this.pageList(doc);
  }

  /** Copia de la página `index` (con sus anotaciones) en la posición `at`. */
  duplicatePage(doc: PdfDocumentObject, index: number, at: number): PdfPageObject[] {
    const ctx = this.context(doc);
    this.forgetPages(ctx);
    const m = this.internals.pdfiumModule;
    const copied = this.withIndices([index], (ptr) => m.FPDF_ImportPagesByIndex(ctx.docPtr, ctx.docPtr, ptr, 1, at));
    if (!copied) throw new Error('No se pudo duplicar la página');
    this.renameAnnotations(ctx, at);
    return this.pageList(doc);
  }

  /**
   * Da a las anotaciones de la página `index` un /NM nuevo. EmbedPDF identifica cada anotación
   * por él: las de una copia no pueden llevar el mismo que las del original.
   */
  private renameAnnotations(ctx: DocumentContext, index: number): void {
    const { pdfiumModule: m } = this.internals;
    ctx.borrowPage(index, ({ pagePtr }) => {
      for (let i = 0; i < m.FPDFPage_GetAnnotCount(pagePtr); i++) {
        const annot = m.FPDFPage_GetAnnot(pagePtr, i);
        if (!annot) continue;
        this.internals.withWString(crypto.randomUUID(), (value) => m.FPDFAnnot_SetStringValue(annot, 'NM', value));
        m.FPDFPage_CloseAnnot(annot);
      }
    });
  }

  // ── Páginas guardadas aparte ───────────────────────────────────────────
  /** Guarda una copia de la página `index` (con sus anotaciones); devuelve su id. */
  stashPage(doc: PdfDocumentObject, index: number): string {
    const ctx = this.context(doc);
    const m = this.internals.pdfiumModule;
    const ptr = m.FPDF_CreateNewDocument();
    if (!ptr) throw new Error('No se pudo guardar la página');
    if (!this.withIndices([index], (indices) => m.FPDF_ImportPagesByIndex(ptr, ctx.docPtr, indices, 1, 0))) {
      m.FPDF_CloseDocument(ptr);
      throw new Error('No se pudo guardar la página');
    }
    const id = `stash-${++this.stashCount}`;
    this.stashes.set(id, { ptr, count: 1 });
    return id;
  }

  /** Devuelve las páginas guardadas en `stash` a la posición `at` (la copia se conserva). */
  restorePages(doc: PdfDocumentObject, stash: string, at: number): PdfPageObject[] {
    const ctx = this.context(doc);
    const saved = this.stashes.get(stash);
    if (!saved) throw new Error('La página guardada ya no existe');
    this.forgetPages(ctx);
    const indices = Array.from({ length: saved.count }, (_, i) => i);
    const m = this.internals.pdfiumModule;
    if (!this.withIndices(indices, (ptr) => m.FPDF_ImportPagesByIndex(ctx.docPtr, saved.ptr, ptr, saved.count, at))) {
      throw new Error('No se pudo devolver la página');
    }
    return this.pageList(doc);
  }

  dropStash(stash: string): boolean {
    const saved = this.stashes.get(stash);
    if (saved) {
      this.internals.pdfiumModule.FPDF_CloseDocument(saved.ptr);
      this.stashes.delete(stash);
    }
    return Boolean(saved);
  }
}

/** Los métodos que añade AppNative (los llama la ventana por su nombre: index.ts). */
export type StructureMethod = 'pageList' | 'rotatePages' | 'movePage' | 'removePage' | 'insertBlankPage' | 'duplicatePage'
  | 'stashPage' | 'restorePages' | 'dropStash';
