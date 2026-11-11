// El motor PDFium de EmbedPDF con lo que le falta para ser el dueño del documento del visor:
// cambiar sus páginas sin volver a abrirlo y sacar copias del documento (para guardarlo,
// imprimirlo o extraer una página) sin el texto del OCR. Corre en el worker (worker.ts); lo prueba
// también Python con el motor real (tests/engine_task.mjs), por eso no depende de nada de la app.
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
  pdfium: {
    HEAPU8: Uint8Array;
    getValue(ptr: number, type: string): number;
    setValue(ptr: number, value: number, type: string): void;
    UTF16ToString(ptr: number): string;
  };
  PDFiumExt_OpenFileWriter(): number;
  PDFiumExt_SaveAsCopy(doc: number, writer: number): boolean;
  PDFiumExt_GetFileWriterSize(writer: number): number;
  PDFiumExt_GetFileWriterData(writer: number, data: number, size: number): number;
  PDFiumExt_CloseFileWriter(writer: number): void;
  FPDF_LoadMemDocument(data: number, size: number, password: string): number;
  FPDF_GetFileVersion(doc: number, version: number): boolean;
  EPDF_IsEncrypted(doc: number): boolean;
  EPDF_RemoveEncryption(doc: number): boolean;
  FPDF_LoadPage(doc: number, index: number): number;
  FPDFPage_CountObjects(page: number): number;
  FPDFPage_GetObject(page: number, index: number): number;
  FPDFPage_RemoveObject(page: number, obj: number): boolean;
  FPDFPage_GenerateContent(page: number): boolean;
  FPDFPageObj_Destroy(obj: number): void;
  FPDFPageObj_CountMarks(obj: number): number;
  FPDFPageObj_GetMark(obj: number, index: number): number;
  FPDFPageObjMark_GetName(mark: number, buffer: number, size: number, length: number): boolean;
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

/** Marca del texto invisible con las palabras del OCR (OCR_MARK en pdf_core/pdf.py). */
const OCR_MARK = 'ExtraerPDFsOCR';
const MARK_NAME_BYTES = 128; // sitio para leer el nombre de una marca (UTF-16)

/** Cómo sacar una copia del documento (`saveCopy`). */
export interface CopyOptions {
  /** Páginas de las que se quita el texto invisible del OCR: es del visor, no va al archivo. */
  withoutText?: number[];
  /** Sin cifrado (para imprimir: el visor de PDF del diálogo pediría la contraseña). */
  decrypt?: boolean;
  /** La contraseña del documento, si está cifrado (para abrir la copia y cambiarla). */
  password?: string | null;
}

/** Lo que el diálogo de propiedades no saca de los metadatos (`documentFacts`). */
export interface DocumentFacts {
  version: string; // «1.7»; vacío si no se sabe
  encrypted: boolean;
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

  // ── Copias del documento ───────────────────────────────────────────────
  /**
   * El PDF entero de `docPtr` (lo usan saveAsCopy, extractPages y las tareas de engine-tasks.ts).
   * Sustituye al de PdfiumNative, que lo copia byte a byte desde el wasm: con un PDF de 47 MB
   * tardaba 890 ms, y así 80 ms.
   */
  override saveDocument(docPtr: number): ArrayBuffer {
    const { pdfiumModule: m, memoryManager } = this.internals;
    const writer = m.PDFiumExt_OpenFileWriter();
    try {
      m.PDFiumExt_SaveAsCopy(docPtr, writer);
      const size = m.PDFiumExt_GetFileWriterSize(writer);
      const data = memoryManager.malloc(size);
      try {
        m.PDFiumExt_GetFileWriterData(writer, data, size);
        return m.pdfium.HEAPU8.slice(data, data + size).buffer;
      } finally {
        memoryManager.free(data);
      }
    } finally {
      m.PDFiumExt_CloseFileWriter(writer);
    }
  }

  /** Copia del documento para guardarla o imprimirla (ver `CopyOptions`). */
  saveCopy(doc: PdfDocumentObject, { withoutText = [], decrypt = false, password = null }: CopyOptions = {}): ArrayBuffer {
    const ctx = this.context(doc);
    const m = this.internals.pdfiumModule;
    const data = this.saveDocument(ctx.docPtr);
    const decrypting = decrypt && m.EPDF_IsEncrypted(ctx.docPtr);
    if (!withoutText.length && !decrypting) return data;
    // Se cambia una copia abierta aparte: el documento a la vista conserva el texto del OCR.
    return this.changedCopy(data, password, (copy) => {
      this.removeOcrText(copy, withoutText);
      if (decrypting) m.EPDF_RemoveEncryption(copy);
    });
  }

  /**
   * Las páginas `indices` como un PDF nuevo (sin cifrar), con sus anotaciones y sin el texto del
   * OCR de las que están en `withoutText` (índices del documento).
   */
  extractCopy(doc: PdfDocumentObject, indices: number[], withoutText: number[] = []): ArrayBuffer {
    const ctx = this.context(doc);
    const m = this.internals.pdfiumModule;
    const copy = m.FPDF_CreateNewDocument();
    if (!copy) throw new Error('No se pudo crear el PDF');
    try {
      if (!this.withIndices(indices, (ptr) => m.FPDF_ImportPagesByIndex(copy, ctx.docPtr, ptr, indices.length, 0))) {
        throw new Error('No se pudieron copiar las páginas');
      }
      this.removeOcrText(copy, indices.flatMap((index, at) => (withoutText.includes(index) ? [at] : [])));
      return this.saveDocument(copy);
    } finally {
      m.FPDF_CloseDocument(copy);
    }
  }

  /** Versión del PDF y si está cifrado (diálogo de propiedades). */
  documentFacts(doc: PdfDocumentObject): DocumentFacts {
    const ctx = this.context(doc);
    const { pdfiumModule: m, memoryManager } = this.internals;
    const ptr = memoryManager.malloc(4);
    try {
      const number = m.FPDF_GetFileVersion(ctx.docPtr, ptr) ? m.pdfium.getValue(ptr, 'i32') : 0;
      const version = number ? `${Math.floor(number / 10)}.${number % 10}` : '';
      return { version, encrypted: Boolean(m.EPDF_IsEncrypted(ctx.docPtr)) };
    } finally {
      memoryManager.free(ptr);
    }
  }

  /** Abre aparte el PDF `data`, lo cambia con `change` y devuelve el resultado. */
  private changedCopy(data: ArrayBuffer, password: string | null, change: (doc: number) => void): ArrayBuffer {
    const { pdfiumModule: m, memoryManager } = this.internals;
    const bytes = new Uint8Array(data);
    const ptr = memoryManager.malloc(bytes.length); // PDFium lo lee mientras está abierto
    try {
      m.pdfium.HEAPU8.set(bytes, ptr);
      const copy = m.FPDF_LoadMemDocument(ptr, bytes.length, password ?? '');
      if (!copy) throw new Error('No se pudo abrir la copia del documento');
      try {
        change(copy);
        return this.saveDocument(copy);
      } finally {
        m.FPDF_CloseDocument(copy);
      }
    } finally {
      memoryManager.free(ptr);
    }
  }

  /** Quita de las páginas `indices` de `docPtr` el texto invisible del OCR (el que lleva OCR_MARK). */
  private removeOcrText(docPtr: number, indices: number[]): void {
    const m = this.internals.pdfiumModule;
    for (const index of indices) {
      const page = m.FPDF_LoadPage(docPtr, index);
      if (!page) continue;
      try {
        let removed = 0;
        for (let i = m.FPDFPage_CountObjects(page) - 1; i >= 0; i--) {
          const obj = m.FPDFPage_GetObject(page, i);
          if (!this.hasOcrMark(obj) || !m.FPDFPage_RemoveObject(page, obj)) continue;
          m.FPDFPageObj_Destroy(obj);
          removed++;
        }
        if (removed) m.FPDFPage_GenerateContent(page);
      } finally {
        m.FPDF_ClosePage(page);
      }
    }
  }

  private hasOcrMark(obj: number): boolean {
    const { pdfiumModule: m, memoryManager } = this.internals;
    const name = memoryManager.malloc(MARK_NAME_BYTES);
    const length = memoryManager.malloc(4);
    try {
      for (let i = 0; i < m.FPDFPageObj_CountMarks(obj); i++) {
        const mark = m.FPDFPageObj_GetMark(obj, i);
        if (!mark || !m.FPDFPageObjMark_GetName(mark, name, MARK_NAME_BYTES, length)) continue;
        if (m.pdfium.UTF16ToString(name) === OCR_MARK) return true;
      }
      return false;
    } finally {
      memoryManager.free(name);
      memoryManager.free(length);
    }
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
export type CopyMethod = 'saveCopy' | 'extractCopy' | 'documentFacts';
