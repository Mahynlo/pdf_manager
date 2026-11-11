// Lo que el OCR del visor necesita del motor: leer una página (`facts`: su texto y dónde tiene
// imágenes), dibujar lo que se va a reconocer (`image`) y escribir las palabras reconocidas como
// texto invisible (`write`), que EmbedPDF selecciona y busca como el nativo. Ese texto lleva la
// marca OCR_MARK: `removeText` lo quita de las copias que salen del visor, porque no va al archivo.
//
// Trabaja con páginas abiertas aparte (FPDF_LoadPage), no con las de EmbedPDF, que las abre
// «normalizadas» (con el giro ya aplicado): así las coordenadas son las del PDF. Quien cambia una
// página tiene que vaciar después la caché de páginas de EmbedPDF (native.ts).
//
// Coordenadas «de vista»: la página tal como se ve (ya girada), en puntos y con el origen arriba
// a la izquierda, como las de Python (pdf_core/pdf.py) y las del lienzo.
import { withMemory, type Memory, type Pdfium } from './pdfium.ts';

/** Rectángulo `[x0, y0, x1, y1]` de vista. */
export type Box = [number, number, number, number];
/** Palabra reconocida: su rectángulo de vista y el texto (como las guarda Python). */
export type OcrWord = [number, number, number, number, string];

/** Lo que dice el texto de una página, sin contar el del OCR, y dónde tiene imágenes. */
export interface PageFacts {
  chars: number; // caracteres que no son espacios
  lines: number; // líneas con texto
  /** Sentido dominante del texto en la vista (`y` hacia abajo; `[1, 0]`: de izquierda a derecha). */
  direction: [number, number];
  images: Box[];
}

/** Una imagen de la página en RGB (3 bytes por píxel, fila a fila), como la espera el OCR. */
export interface PageImage {
  width: number;
  height: number;
  data: ArrayBuffer;
}

/** Las palabras que se escriben en una página; `replace`: antes se quita el texto del OCR que tenía. */
export interface OcrText {
  index: number;
  words: OcrWord[];
  replace: boolean;
}

/** Marca del texto invisible con las palabras del OCR (la buscan las copias para quitarlo). */
export const OCR_MARK = 'ExtraerPDFsOCR';
const MARK_NAME_BYTES = 128; // sitio para leer el nombre de una marca (UTF-16)
const OCR_FONT = 'Helvetica';
const FONT_SIZE = 12; // el texto se escala después a su rectángulo
const COVERED = 0.4; // una palabra tapada en esta parte por texto nativo ya está en la página
const BAND = 10; // pt: franjas para buscar el texto nativo que tapa una palabra
// Constantes de PDFium
const OBJ_TEXT = 1;
const OBJ_IMAGE = 3;
const OBJ_FORM = 5;
const TEXT_INVISIBLE = 3;
const BITMAP_BGRA = 4;
const WHITE = 0xffffffff;
const DRAW_ANNOTS = 0x01;
const REVERSE_BYTE_ORDER = 0x10; // RGBA en vez de BGRA
const NEWLINE = 0x0a;
const SPACE = 0x20;

type Matrix = [number, number, number, number, number, number];
const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

/** Medidas de una página: su caja visible sin girar (en el PDF, origen abajo) y su giro. */
interface Geometry {
  width: number;
  height: number;
  left: number;
  top: number;
  rotation: number; // grados
}

export class PageOcr {
  // Sin propiedades en los parámetros del constructor: Node (las pruebas) solo quita los tipos.
  private m: Pdfium;
  private memory: Memory;
  private withWString: <T>(value: string, fn: (ptr: number) => T) => T;

  constructor(m: Pdfium, memory: Memory, withWString: <T>(value: string, fn: (ptr: number) => T) => T) {
    this.m = m;
    this.memory = memory;
    this.withWString = withWString;
  }

  // ── Leer ───────────────────────────────────────────────────────────────
  facts(docPtr: number, index: number): PageFacts {
    return this.withPage(docPtr, index, (page, geo) => {
      const facts: PageFacts = { chars: 0, lines: 0, direction: [0, 0], images: [] };
      const lines = new Set<number>();
      const turn = (geo.rotation * Math.PI) / 180;
      this.eachChar(page, (text, i, line) => {
        lines.add(line);
        facts.chars++;
        if (this.m.FPDFText_IsGenerated(text, i) === 1) return;
        const angle = this.m.FPDFText_GetCharAngle(text, i); // horario, como /Rotate
        if (angle < 0) return;
        facts.direction[0] += Math.cos(angle + turn);
        facts.direction[1] += Math.sin(angle + turn);
      });
      facts.lines = lines.size;
      this.eachImage(page, (matrix) => {
        const corners = [[0, 0], [1, 0], [0, 1], [1, 1]].map(([x, y]) => apply(matrix, x, y));
        const xs = corners.map(([x]) => x);
        const ys = corners.map(([, y]) => y);
        facts.images.push(toView(geo, fromPdf(geo, Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys))));
      });
      return facts;
    });
  }

  /** La página tal como se ve (con sus anotaciones) a `scale` píxeles por punto; `clip`: solo ese trozo. */
  image(docPtr: number, index: number, scale: number, clip?: Box): PageImage {
    return this.withPage(docPtr, index, (page) => {
      const [x0, y0, x1, y1] = clip ?? [0, 0, this.m.FPDF_GetPageWidthF(page), this.m.FPDF_GetPageHeightF(page)];
      const width = Math.max(1, Math.round((x1 - x0) * scale));
      const height = Math.max(1, Math.round((y1 - y0) * scale));
      return withMemory(this.memory, width * height * 4, (pixels) => {
        const bitmap = this.m.FPDFBitmap_CreateEx(width, height, BITMAP_BGRA, pixels, width * 4);
        if (!bitmap) throw new Error('No se pudo dibujar la página');
        try {
          this.m.FPDFBitmap_FillRect(bitmap, 0, 0, width, height, WHITE);
          // La matriz va de la página vista a 1 px por punto a la imagen.
          this.withFloats([scale, 0, 0, scale, -x0 * scale, -y0 * scale], (matrix) =>
            this.withFloats([0, 0, width, height], (area) =>
              this.m.FPDF_RenderPageBitmapWithMatrix(bitmap, page, matrix, area, DRAW_ANNOTS | REVERSE_BYTE_ORDER)));
        } finally {
          this.m.FPDFBitmap_Destroy(bitmap);
        }
        const rgba = this.m.pdfium.HEAPU8.subarray(pixels, pixels + width * height * 4);
        const rgb = new Uint8Array(width * height * 3);
        for (let src = 0, dst = 0; src < rgba.length; src += 4, dst += 3) {
          rgb[dst] = rgba[src];
          rgb[dst + 1] = rgba[src + 1];
          rgb[dst + 2] = rgba[src + 2];
        }
        return { width, height, data: rgb.buffer };
      });
    });
  }

  // ── Escribir ───────────────────────────────────────────────────────────
  /**
   * Escribe las palabras de la página como texto invisible: cada una ocupa su rectángulo y se lee
   * en el sentido en que se ve la página. Se saltan las que tapa el texto nativo (ya están).
   * Devuelve si cambió la página.
   */
  write(docPtr: number, { index, words, replace }: OcrText): boolean {
    return this.withPage(docPtr, index, (page, geo) => {
      let changed = replace && this.removeFrom(page) > 0;
      const covered = this.coverage(page, geo);
      const font = this.m.FPDFText_LoadStandardFont(docPtr, OCR_FONT);
      if (!font) throw new Error('No se pudo cargar la fuente del texto del OCR');
      try {
        for (const [x0, y0, x1, y1, text] of words) {
          const box: Box = [x0, y0, x1, y1];
          if (!text.trim() || x1 <= x0 || y1 <= y0 || covered(box)) continue;
          changed = this.addWord(docPtr, page, geo, font, box, text.trim()) || changed;
        }
      } finally {
        this.m.FPDFFont_Close(font);
      }
      if (changed) this.m.FPDFPage_GenerateContent(page);
      return changed;
    });
  }

  /** Quita de las páginas `indices` de `docPtr` el texto invisible del OCR. */
  removeText(docPtr: number, indices: number[]): void {
    for (const index of indices) {
      this.withPage(docPtr, index, (page) => {
        if (this.removeFrom(page)) this.m.FPDFPage_GenerateContent(page);
      });
    }
  }

  private addWord(docPtr: number, page: number, geo: Geometry, font: number, box: Box, text: string): boolean {
    const { m } = this;
    const obj = m.FPDFPageObj_CreateTextObj(docPtr, font, FONT_SIZE);
    if (!obj) return false;
    this.withWString(text, (ptr) => m.FPDFText_SetText(obj, ptr));
    m.FPDFTextObj_SetTextRenderMode(obj, TEXT_INVISIBLE);
    m.FPDFPageObj_AddMark(obj, OCR_MARK);
    const bounds = withMemory(this.memory, 16, (ptr) => {
      const ok = m.FPDFPageObj_GetBounds(obj, ptr, ptr + 4, ptr + 8, ptr + 12);
      return ok ? [0, 4, 8, 12].map((offset) => m.pdfium.getValue(ptr + offset, 'float')) : null;
    });
    const [left, bottom, right, top] = bounds ?? [0, 0, 0, 0];
    if (right <= left || top <= bottom) {
      m.FPDFPageObj_Destroy(obj);
      return false;
    }
    m.FPDFPageObj_Transform(obj, ...fit(geo, box, left, bottom, right - left, top - bottom));
    m.FPDFPage_InsertObject(page, obj);
    return true;
  }

  /** Quita de `page` los objetos con la marca del OCR; devuelve cuántos. */
  private removeFrom(page: number): number {
    const { m } = this;
    let removed = 0;
    for (let i = m.FPDFPage_CountObjects(page) - 1; i >= 0; i--) {
      const obj = m.FPDFPage_GetObject(page, i);
      if (!this.hasOcrMark(obj) || !m.FPDFPage_RemoveObject(page, obj)) continue;
      m.FPDFPageObj_Destroy(obj);
      removed++;
    }
    return removed;
  }

  /** Función que dice si un rectángulo de vista queda tapado por el texto nativo de `page`. */
  private coverage(page: number, geo: Geometry): (box: Box) => boolean {
    const bands = new Map<number, Box[]>();
    this.withFloats([0, 0, 0, 0], (rect) => {
      this.eachChar(page, (text, i) => {
        if (!this.m.FPDFText_GetLooseCharBox(text, i, rect)) return;
        const [left, top, right, bottom] = [0, 4, 8, 12].map((offset) => this.m.pdfium.getValue(rect + offset, 'float'));
        const box = toView(geo, fromPdf(geo, left, bottom, right, top));
        for (let band = Math.floor(box[1] / BAND); band <= Math.floor(box[3] / BAND); band++) {
          const list = bands.get(band);
          if (list) list.push(box);
          else bands.set(band, [box]);
        }
      });
    });
    return (box) => {
      const area = (box[2] - box[0]) * (box[3] - box[1]);
      const seen = new Set<Box>();
      let covered = 0;
      for (let band = Math.floor(box[1] / BAND); band <= Math.floor(box[3] / BAND); band++) {
        for (const other of bands.get(band) ?? []) {
          if (seen.has(other)) continue;
          const w = Math.min(box[2], other[2]) - Math.max(box[0], other[0]);
          const h = Math.min(box[3], other[3]) - Math.max(box[1], other[1]);
          if (w <= 0 || h <= 0) continue;
          seen.add(other);
          covered += w * h;
          if (covered >= area * COVERED) return true;
        }
      }
      return false;
    };
  }

  // ── Recorrer la página ─────────────────────────────────────────────────
  /** Abre aparte la página `index`, con sus medidas, mientras dura `fn`. */
  private withPage<T>(docPtr: number, index: number, fn: (page: number, geo: Geometry) => T): T {
    const page = this.m.FPDF_LoadPage(docPtr, index);
    if (!page) throw new Error(`No se pudo abrir la página ${index + 1}`);
    try {
      return fn(page, this.geometry(page));
    } finally {
      this.m.FPDF_ClosePage(page);
    }
  }

  private geometry(page: number): Geometry {
    const { m } = this;
    const rotation = (m.FPDFPage_GetRotation(page) % 4) * 90;
    return this.withFloats([0, 0, 0, 0], (rect) => {
      if (m.FPDF_GetPageBoundingBox(page, rect)) {
        const [left, top, right, bottom] = [0, 4, 8, 12].map((offset) => m.pdfium.getValue(rect + offset, 'float'));
        return { width: right - left, height: top - bottom, left, top, rotation };
      }
      const [w, h] = [m.FPDF_GetPageWidthF(page), m.FPDF_GetPageHeightF(page)]; // ya girada
      const [width, height] = rotation % 180 ? [h, w] : [w, h];
      return { width, height, left: 0, top: height, rotation };
    });
  }

  /**
   * Llama a `fn` por cada carácter de la página que no es un espacio ni del OCR, con el número de
   * su línea (el texto, sin girar la página, como lo ordena PDFium).
   */
  private eachChar(page: number, fn: (text: number, index: number, line: number) => void): void {
    const { m } = this;
    const text = m.FPDFText_LoadPage(page);
    if (!text) return;
    const ocr = new Map<number, boolean>(); // objeto de texto -> lleva la marca
    try {
      let line = 0;
      for (let i = 0; i < m.FPDFText_CountChars(text); i++) {
        const code = m.FPDFText_GetUnicode(text, i);
        if (code === NEWLINE) line++;
        if (code <= SPACE) continue;
        const obj = m.FPDFText_GetTextObject(text, i);
        if (obj) {
          if (!ocr.has(obj)) ocr.set(obj, this.hasOcrMark(obj));
          if (ocr.get(obj)) continue;
        }
        fn(text, i, line);
      }
    } finally {
      m.FPDFText_ClosePage(text);
    }
  }

  /** Llama a `fn` con la matriz (hasta la página) de cada imagen, también dentro de Form XObjects. */
  private eachImage(page: number, fn: (matrix: Matrix) => void): void {
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

  private matrix(obj: number): Matrix {
    return this.withFloats([...IDENTITY], (ptr) =>
      this.m.FPDFPageObj_GetMatrix(obj, ptr)
        ? ([0, 1, 2, 3, 4, 5].map((i) => this.m.pdfium.getValue(ptr + i * 4, 'float')) as Matrix)
        : IDENTITY);
  }

  private hasOcrMark(obj: number): boolean {
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
  private withFloats<T>(values: number[], fn: (ptr: number) => T): T {
    return withMemory(this.memory, values.length * 4, (ptr) => {
      values.forEach((value, i) => this.m.pdfium.setValue(ptr + i * 4, value, 'float'));
      return fn(ptr);
    });
  }
}

// ── Coordenadas ──────────────────────────────────────────────────────────
/** De PDFium (origen abajo, absolutas) a la página sin girar con el origen arriba. */
function fromPdf(geo: Geometry, left: number, bottom: number, right: number, top: number): Box {
  return [left - geo.left, geo.top - top, right - geo.left, geo.top - bottom];
}

/** De la página sin girar a la vista (Page.to_view en pdf_core/pdf.py). */
function toView({ width: w, height: h, rotation }: Geometry, [x0, y0, x1, y1]: Box): Box {
  if (rotation === 90) return [h - y1, x0, h - y0, x1];
  if (rotation === 180) return [w - x1, h - y1, w - x0, h - y0];
  if (rotation === 270) return [y0, w - x1, y1, w - x0];
  return [x0, y0, x1, y1];
}

/**
 * Matriz que lleva la caja de un texto recién creado (`left`, `bottom`, `width`, `height` en el
 * PDF) al rectángulo de vista `box`. Pasa por un espacio con `y` hacia arriba alineado con la
 * vista; de ahí a la página según su giro (inverso del /Rotate) y a su caja visible.
 */
function fit(geo: Geometry, [x0, y0, x1, y1]: Box, left: number, bottom: number, width: number, height: number): Matrix {
  const sx = (x1 - x0) / width;
  const sy = (y1 - y0) / height;
  const viewHeight = geo.rotation % 180 ? geo.width : geo.height;
  // En ese espacio: u = sx (x - left) + u0 ; v = sy (y - bottom) + v0
  const u0 = x0 - sx * left;
  const v0 = viewHeight - y1 - sy * bottom;
  const { width: w, height: h } = geo;
  let m: Matrix;
  if (geo.rotation === 90) m = [0, sx, -sy, 0, w - v0, u0]; // x = w - v ; y = u
  else if (geo.rotation === 180) m = [-sx, 0, 0, -sy, w - u0, h - v0]; // x = w - u ; y = h - v
  else if (geo.rotation === 270) m = [0, -sx, sy, 0, v0, h - u0]; // x = v ; y = h - u
  else m = [sx, 0, 0, sy, u0, v0];
  return [m[0], m[1], m[2], m[3], m[4] + geo.left, m[5] + geo.top - geo.height];
}

function apply(m: Matrix, x: number, y: number): [number, number] {
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
