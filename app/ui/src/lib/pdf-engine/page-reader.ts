// Leer una página del documento fuera de EmbedPDF: la base de lo que hacen con las páginas el OCR
// (page-ocr.ts) y el texto que recibe Python (page-text.ts).
//
// Trabaja con páginas abiertas aparte (FPDF_LoadPage), no con las de EmbedPDF, que las abre
// «normalizadas» (con el giro ya aplicado): así las coordenadas son las del PDF. Quien cambia una
// página tiene que vaciar después la caché de páginas de EmbedPDF (native.ts).
//
// Coordenadas «de página»: la página sin girar, en puntos y con el origen arriba a la izquierda;
// «de vista»: la página tal como se ve (ya girada). Las mismas que en Python (pdf_core/pdf.py).
import { withMemory, type Memory, type Pdfium } from './pdfium.ts';

/** Rectángulo `[x0, y0, x1, y1]` en puntos. */
export type Box = [number, number, number, number];
export type Matrix = [number, number, number, number, number, number];

/** Medidas de una página: su caja visible sin girar (en el PDF, origen abajo) y su giro. */
export interface Geometry {
  width: number;
  height: number;
  left: number;
  top: number;
  rotation: number; // grados
}

/** Marca del texto invisible con las palabras del OCR: no es texto de la página. */
export const OCR_MARK = 'ExtraerPDFsOCR';
const MARK_NAME_BYTES = 128; // sitio para leer el nombre de una marca (UTF-16)
// Constantes de PDFium
const OBJ_TEXT = 1;
const OBJ_IMAGE = 3;
const OBJ_FORM = 5;
const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

/** Un carácter del texto de la página (no del OCR), con el número de su línea. */
export interface CharVisit {
  text: number; // la página de texto de PDFium
  index: number; // el carácter en ella
  code: number; // su código Unicode
  line: number;
}

export class PageReader {
  // Sin propiedades en los parámetros del constructor: Node (las pruebas) solo quita los tipos.
  readonly m: Pdfium;
  readonly memory: Memory;

  constructor(m: Pdfium, memory: Memory) {
    this.m = m;
    this.memory = memory;
  }

  /** Abre aparte la página `index`, con sus medidas, mientras dura `fn`. */
  withPage<T>(docPtr: number, index: number, fn: (page: number, geo: Geometry) => T): T {
    const page = this.m.FPDF_LoadPage(docPtr, index);
    if (!page) throw new Error(`No se pudo abrir la página ${index + 1}`);
    try {
      return fn(page, this.geometry(page));
    } finally {
      this.m.FPDF_ClosePage(page);
    }
  }

  geometry(page: number): Geometry {
    const { m } = this;
    const rotation = (m.FPDFPage_GetRotation(page) % 4) * 90;
    return this.withFloats([0, 0, 0, 0], (rect) => {
      if (m.FPDF_GetPageBoundingBox(page, rect)) {
        const [left, top, right, bottom] = this.floats(rect, 4);
        return { width: right - left, height: top - bottom, left, top, rotation };
      }
      const [w, h] = [m.FPDF_GetPageWidthF(page), m.FPDF_GetPageHeightF(page)]; // ya girada
      const [width, height] = rotation % 180 ? [h, w] : [w, h];
      return { width, height, left: 0, top: height, rotation };
    });
  }

  /**
   * Llama a `fn` por cada carácter del texto de la página, sin el del OCR, en el orden de PDFium.
   * Los espacios y saltos de línea entre el texto de la página y el del OCR no cuentan: solo se
   * pasan los que van delante de otro carácter de la página. `unrotated`: el texto se ordena con la
   * página sin girar (así se lee en su sentido original, como en Python).
   */
  eachChar(page: number, fn: (char: CharVisit) => void, { unrotated = false } = {}): void {
    const { m } = this;
    const withOcr = this.hasOcrText(page);
    const rotation = m.FPDFPage_GetRotation(page);
    if (unrotated && rotation) m.FPDFPage_SetRotation(page, 0);
    const text = m.FPDFText_LoadPage(page);
    try {
      if (!text) return;
      if (!withOcr) {
        // Lo normal: sin texto del OCR, todos los caracteres son de la página.
        const count = m.FPDFText_CountChars(text);
        const codes = this.codes(text, count);
        let line = 0;
        for (let index = 0; index < count; index++) {
          const code = codes ? codes[index] : m.FPDFText_GetUnicode(text, index);
          fn({ text, index, code, line });
          if (code === 0x0a) line++;
        }
        return;
      }
      const ocr = new Map<number, boolean>(); // objeto de texto -> lleva la marca
      let pending: CharVisit[] = []; // espacios y saltos aún sin un carácter detrás
      let skipped = false; // entre ellos hay texto del OCR
      let line = 0;
      for (let index = 0; index < m.FPDFText_CountChars(text); index++) {
        const code = m.FPDFText_GetUnicode(text, index);
        const obj = m.FPDFText_GetTextObject(text, index);
        if (obj) {
          if (!ocr.has(obj)) ocr.set(obj, this.hasOcrMark(obj));
          if (ocr.get(obj)) {
            skipped = true;
            continue;
          }
        }
        const visit = { text, index, code, line };
        if (code === 0x0a) line++;
        if (!obj || code <= 0x20) {
          pending.push(visit); // un espacio o un salto (los genera PDFium)
          continue;
        }
        // Alrededor del texto del OCR queda un solo separador: el salto de línea, si lo había.
        if (skipped) pending = [pending.find((space) => space.code === 0x0a) ?? pending[0]].filter(Boolean);
        for (const space of pending) fn(space);
        pending = [];
        skipped = false;
        fn(visit);
      }
    } finally {
      if (text) m.FPDFText_ClosePage(text);
      if (unrotated && rotation) m.FPDFPage_SetRotation(page, rotation);
    }
  }

  /**
   * La caja holgada (con la altura de la fuente) de un carácter, en el PDF: `[izquierda, abajo,
   * derecha, arriba]`; null si no tiene. `rect`: 4 floats del wasm donde leerla.
   */
  looseBox({ text, index }: CharVisit, rect: number): [number, number, number, number] | null {
    if (!this.m.FPDFText_GetLooseCharBox(text, index, rect)) return null;
    const heap = this.m.pdfium.HEAPF32; // FS_RECTF: izquierda, arriba, derecha, abajo
    const at = rect >> 2;
    return [heap[at], heap[at + 3], heap[at + 2], heap[at + 1]];
  }

  /**
   * El código de cada carácter de la página de texto, de una vez (FPDFText_GetText, en UTF-16);
   * null si no se corresponde uno a uno (caracteres fuera del plano básico: van en dos unidades).
   */
  private codes(text: number, count: number): Uint16Array | null {
    if (!count) return new Uint16Array(0);
    return withMemory(this.memory, (count + 1) * 2, (buffer) => {
      const written = this.m.FPDFText_GetText(text, 0, count, buffer);
      if (written !== count + 1) return null;
      const codes = this.m.pdfium.HEAPU8.slice(buffer, buffer + count * 2);
      const units = new Uint16Array(codes.buffer);
      return units.some((unit) => unit >= 0xd800 && unit <= 0xdfff) ? null : units;
    });
  }

  /** Si la página tiene texto del OCR (algún objeto con la marca). */
  hasOcrText(page: number): boolean {
    for (let i = 0; i < this.m.FPDFPage_CountObjects(page); i++) {
      if (this.hasOcrMark(this.m.FPDFPage_GetObject(page, i))) return true;
    }
    return false;
  }

  /** Llama a `fn` con la matriz (hasta la página) de cada imagen, también dentro de Form XObjects. */
  eachImage(page: number, fn: (matrix: Matrix) => void): void {
    const walk = (count: number, get: (i: number) => number, parent: Matrix): void => {
      for (let i = 0; i < count; i++) {
        const obj = get(i);
        const type = this.m.FPDFPageObj_GetType(obj);
        if (type !== OBJ_IMAGE && type !== OBJ_FORM) continue;
        const matrix = compose(this.matrix(obj), parent);
        if (type === OBJ_IMAGE) fn(matrix);
        else walk(this.m.FPDFFormObj_CountObjects(obj), (k) => this.m.FPDFFormObj_GetObject(obj, k), matrix);
      }
    };
    walk(this.m.FPDFPage_CountObjects(page), (i) => this.m.FPDFPage_GetObject(page, i), IDENTITY);
  }

  /** Si el objeto es texto del OCR (lleva OCR_MARK). */
  hasOcrMark(obj: number): boolean {
    const { m } = this;
    if (m.FPDFPageObj_GetType(obj) !== OBJ_TEXT) return false;
    return withMemory(this.memory, MARK_NAME_BYTES, (name) => withMemory(this.memory, 4, (length) => {
      for (let i = 0; i < m.FPDFPageObj_CountMarks(obj); i++) {
        const mark = m.FPDFPageObj_GetMark(obj, i);
        if (mark && m.FPDFPageObjMark_GetName(mark, name, MARK_NAME_BYTES, length) && m.pdfium.UTF16ToString(name) === OCR_MARK) {
          return true;
        }
      }
      return false;
    }));
  }

  /** Llama a `fn` con un float[] del wasm que empieza con `values`. */
  withFloats<T>(values: number[], fn: (ptr: number) => T): T {
    return withMemory(this.memory, values.length * 4, (ptr) => {
      values.forEach((value, i) => this.m.pdfium.setValue(ptr + i * 4, value, 'float'));
      return fn(ptr);
    });
  }

  /** Los `count` floats del wasm desde `ptr`. */
  floats(ptr: number, count: number): number[] {
    return Array.from({ length: count }, (_, i) => this.m.pdfium.getValue(ptr + i * 4, 'float'));
  }

  private matrix(obj: number): Matrix {
    return this.withFloats([...IDENTITY], (ptr) => (this.m.FPDFPageObj_GetMatrix(obj, ptr) ? (this.floats(ptr, 6) as Matrix) : IDENTITY));
  }
}

// ── Coordenadas ──────────────────────────────────────────────────────────
/** De PDFium (origen abajo, absolutas) a la página sin girar con el origen arriba. */
export function fromPdf(geo: Geometry, left: number, bottom: number, right: number, top: number): Box {
  return [left - geo.left, geo.top - top, right - geo.left, geo.top - bottom];
}

/** De la página sin girar a la vista (PageGeometry.to_view en pdf_core/pdf.py). */
export function toView({ width: w, height: h, rotation }: Geometry, [x0, y0, x1, y1]: Box): Box {
  if (rotation === 90) return [h - y1, x0, h - y0, x1];
  if (rotation === 180) return [w - x1, h - y1, w - x0, h - y0];
  if (rotation === 270) return [y0, w - x1, y1, w - x0];
  return [x0, y0, x1, y1];
}

export function apply(m: Matrix, x: number, y: number): [number, number] {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

/** Primero `inner` y después `outer`. */
function compose([a, b, c, d, e, f]: Matrix, outer: Matrix): Matrix {
  return [
    a * outer[0] + b * outer[2], a * outer[1] + b * outer[3],
    c * outer[0] + d * outer[2], c * outer[1] + d * outer[3],
    e * outer[0] + f * outer[2] + outer[4], e * outer[1] + f * outer[3] + outer[5],
  ];
}
