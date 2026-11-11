// Lo que el motor de la app usa directamente del PDFium de EmbedPDF (todas estas funciones están en
// su wasm, `@embedpdf/pdfium`) y las partes privadas de PdfiumNative 2.15.1 que necesita: revisarlas
// al actualizar EmbedPDF.

/** Las funciones de PDFium que se llaman directamente. */
export interface Pdfium {
  pdfium: {
    HEAPU8: Uint8Array;
    HEAPF32: Float32Array; // la misma memoria: se lee de nuevo cada vez (cambia si la memoria crece)
    getValue(ptr: number, type: string): number;
    setValue(ptr: number, value: number, type: string): void;
    UTF16ToString(ptr: number): string;
  };
  // Documento
  PDFiumExt_OpenFileWriter(): number;
  PDFiumExt_SaveAsCopy(doc: number, writer: number): boolean;
  PDFiumExt_GetFileWriterSize(writer: number): number;
  PDFiumExt_GetFileWriterData(writer: number, data: number, size: number): number;
  PDFiumExt_CloseFileWriter(writer: number): void;
  FPDF_LoadMemDocument(data: number, size: number, password: string): number;
  FPDF_CreateNewDocument(): number;
  FPDF_CloseDocument(doc: number): void;
  FPDF_GetFileVersion(doc: number, version: number): boolean;
  EPDF_IsEncrypted(doc: number): boolean;
  EPDF_RemoveEncryption(doc: number): boolean;
  // Páginas
  FPDF_GetPageCount(doc: number): number;
  FPDF_GetPageSizeByIndexF(doc: number, index: number, size: number): boolean;
  EPDF_GetPageSizeByIndexNormalized(doc: number, index: number, size: number): boolean;
  EPDF_GetPageRotationByIndex(doc: number, index: number): number;
  EPDFDoc_GetPageObjectNumberByIndex(doc: number, index: number): number;
  FPDF_LoadPage(doc: number, index: number): number;
  FPDF_ClosePage(page: number): void;
  FPDFPage_New(doc: number, index: number, width: number, height: number): number;
  FPDFPage_Delete(doc: number, index: number): void;
  FPDF_MovePages(doc: number, indices: number, count: number, dest: number): boolean;
  FPDF_ImportPagesByIndex(dest: number, src: number, indices: number, count: number, at: number): boolean;
  FPDFPage_GetRotation(page: number): number;
  FPDFPage_SetRotation(page: number, rotation: number): void;
  FPDF_GetPageBoundingBox(page: number, rect: number): boolean;
  FPDF_GetPageWidthF(page: number): number;
  FPDF_GetPageHeightF(page: number): number;
  // Objetos de página
  FPDFPage_CountObjects(page: number): number;
  FPDFPage_GetObject(page: number, index: number): number;
  FPDFPage_InsertObject(page: number, obj: number): void;
  FPDFPage_RemoveObject(page: number, obj: number): boolean;
  FPDFPage_GenerateContent(page: number): boolean;
  FPDFPageObj_Destroy(obj: number): void;
  FPDFPageObj_GetType(obj: number): number;
  FPDFPageObj_GetMatrix(obj: number, matrix: number): boolean;
  FPDFPageObj_GetBounds(obj: number, left: number, bottom: number, right: number, top: number): boolean;
  FPDFPageObj_Transform(obj: number, a: number, b: number, c: number, d: number, e: number, f: number): void;
  FPDFPageObj_CountMarks(obj: number): number;
  FPDFPageObj_GetMark(obj: number, index: number): number;
  FPDFPageObj_AddMark(obj: number, name: string): number;
  FPDFPageObjMark_GetName(mark: number, buffer: number, size: number, length: number): boolean;
  FPDFFormObj_CountObjects(form: number): number;
  FPDFFormObj_GetObject(form: number, index: number): number;
  // Texto
  FPDFText_LoadPage(page: number): number;
  FPDFText_ClosePage(text: number): void;
  FPDFText_CountChars(text: number): number;
  FPDFText_GetUnicode(text: number, index: number): number;
  FPDFText_GetText(text: number, start: number, count: number, buffer: number): number;
  FPDFText_IsGenerated(text: number, index: number): number;
  FPDFText_GetCharAngle(text: number, index: number): number;
  FPDFText_GetLooseCharBox(text: number, index: number, rect: number): boolean;
  FPDFText_GetTextObject(text: number, index: number): number;
  FPDFText_LoadStandardFont(doc: number, name: string): number;
  FPDFFont_Close(font: number): void;
  FPDFPageObj_CreateTextObj(doc: number, font: number, size: number): number;
  FPDFText_SetText(obj: number, text: number): boolean;
  FPDFTextObj_SetTextRenderMode(obj: number, mode: number): boolean;
  // Dibujar
  FPDFBitmap_CreateEx(width: number, height: number, format: number, buffer: number, stride: number): number;
  FPDFBitmap_FillRect(bitmap: number, left: number, top: number, width: number, height: number, color: number): void;
  FPDFBitmap_Destroy(bitmap: number): void;
  FPDF_RenderPageBitmapWithMatrix(bitmap: number, page: number, matrix: number, clip: number, flags: number): void;
  // Anotaciones
  FPDFPage_GetAnnotCount(page: number): number;
  FPDFPage_GetAnnot(page: number, index: number): number;
  FPDFPage_CloseAnnot(annot: number): void;
  FPDFAnnot_SetStringValue(annot: number, key: string, value: number): boolean;
}

/** La memoria del wasm (el gestor de PdfiumNative). */
export interface Memory {
  malloc(size: number): number;
  free(ptr: number): void;
}

/** Lo privado de PdfiumNative que se usa. */
export interface Internals {
  cache: { getContext(id: string): DocumentContext | undefined };
  pdfiumModule: Pdfium;
  memoryManager: Memory;
  withWString<T>(value: string, fn: (ptr: number) => T): T;
}

/** Un documento abierto en PdfiumNative. */
export interface DocumentContext {
  docPtr: number;
  normalizeRotation: boolean;
  pageCache: { forceReleaseAll(): void };
  borrowPage<T>(index: number, fn: (page: { pagePtr: number }) => T): T;
}

/** Llama a `fn` con `size` bytes de memoria del wasm, que se sueltan al terminar. */
export function withMemory<T>(memory: Memory, size: number, fn: (ptr: number) => T): T {
  const ptr = memory.malloc(size);
  try {
    return fn(ptr);
  } finally {
    memory.free(ptr);
  }
}
