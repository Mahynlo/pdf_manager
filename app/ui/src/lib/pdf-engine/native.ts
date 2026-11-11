// El motor PDFium de EmbedPDF con lo que le falta para ser el dueño del documento del visor:
// cambiar sus páginas sin volver a abrirlo, sacar copias del documento (para guardarlo,
// imprimirlo o extraer una página) sin el texto del OCR, y leer, dibujar y escribir lo que
// necesita el OCR (page-ocr.ts). Corre en el worker (worker.ts); lo prueba también Python con el
// motor real (tests/engine_task.mjs), por eso no depende de nada de la app.
//
// Usa partes privadas de PdfiumNative 2.15.1 (`Internals`, en pdfium.ts): revisarlas al
// actualizar EmbedPDF.
import { PdfiumNative } from '@embedpdf/engines/pdfium';
import type { PdfDocumentObject, PdfPageObject } from '@embedpdf/models';
import { PageOcr, type OcrText, type PageFacts, type PageImage, type Box } from './page-ocr.ts';
import type { DocumentContext, Internals } from './pdfium.ts';

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
  private pageOcr: PageOcr | null = null;

  private get internals(): Internals {
    return this as unknown as Internals;
  }

  /** Se crea al usarlo: el módulo de PDFium lo pone el constructor de PdfiumNative. */
  private get ocr(): PageOcr {
    const { pdfiumModule, memoryManager } = this.internals;
    this.pageOcr ??= new PageOcr(pdfiumModule, memoryManager, (value, fn) => this.internals.withWString(value, fn));
    return this.pageOcr;
  }

  private context(doc: PdfDocumentObject): DocumentContext {
    const ctx = this.internals.cache.getContext(doc.id);
    if (!ctx) throw new Error(`El documento ${doc.id} no está abierto`);
    return ctx;
  }

  /**
   * Antes de cambiar el orden (la caché de páginas va por número de página, que cambia) y después
   * de cambiar una página aparte (la que tiene abierta EmbedPDF ya no vale).
   */
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
      this.ocr.removeText(copy, withoutText);
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
      this.ocr.removeText(copy, indices.flatMap((index, at) => (withoutText.includes(index) ? [at] : [])));
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

  // ── OCR ────────────────────────────────────────────────────────────────
  /** El texto de la página `index` (sin el del OCR) y dónde tiene imágenes. */
  pageFacts(doc: PdfDocumentObject, index: number): PageFacts {
    return this.ocr.facts(this.context(doc).docPtr, index);
  }

  /** La página `index` tal como se ve, a `scale` píxeles por punto; `clip`: solo ese trozo. */
  pageImage(doc: PdfDocumentObject, index: number, scale: number, clip?: Box): PageImage {
    return this.ocr.image(this.context(doc).docPtr, index, scale, clip);
  }

  /** Escribe en el documento las palabras del OCR (texto invisible); devuelve las páginas que cambiaron. */
  writeOcrText(doc: PdfDocumentObject, pages: OcrText[]): number[] {
    const ctx = this.context(doc);
    const changed = pages.filter((page) => this.ocr.write(ctx.docPtr, page)).map((page) => page.index);
    // Las páginas que tiene abiertas EmbedPDF (y su texto) son anteriores al cambio.
    if (changed.length) this.forgetPages(ctx);
    return changed;
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
export type OcrMethod = 'pageFacts' | 'pageImage' | 'writeOcrText';
