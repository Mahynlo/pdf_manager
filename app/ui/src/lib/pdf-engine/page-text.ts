// El texto de las páginas, para Python: lo usa su capa de texto en orden de lectura (asistente IA,
// panel del OCR, exportar texto) y la búsqueda de la censura. Python no tiene el documento del
// visor: recibe esto (pdf_core.pdf.PageText) de las páginas cuyo texto aún no tiene.
//
// Es lo mismo que lee Python de un PDF (Page.chars en pdf_core/pdf.py): cada carácter en el orden
// de PDFium con la página sin girar, también espacios y saltos de línea, con su caja holgada en
// coordenadas de página y su línea. Sin el texto del OCR, que Python guarda aparte.
import { fromPdf, type Geometry, type PageReader } from './page-reader.ts';

/** Las medidas de una página: `[ancho, alto, izquierda, arriba, giro]` (PageGeometry en Python). */
export type GeometryTuple = [number, number, number, number, number];

/** El texto de unas páginas: `pages[i]` dice cuántos caracteres de `data` son suyos. */
export interface PageTexts {
  pages: { index: number; geometry: GeometryTuple; count: number }[];
  /**
   * Por cada página, uno tras otro: el código Unicode de cada carácter (uint32), su caja
   * `[x0, y0, x1, y1]` (4 float32; ceros si no tiene) y su línea (uint32).
   */
  data: ArrayBuffer;
}

const BYTES_PER_CHAR = 4 + 16 + 4;
const SKIPPED = new Set([0, 0x0d]); // nada y el retorno de carro (el salto es 0x0a)
const HYPHENS = new Set([0x02, 0xfffe]); // guion de fin de línea según PDFium
const HYPHEN = 0x2d;
const INITIAL_CHARS = 2048;

/** El texto de una página, ya en los arrays que recibe Python. */
interface PackedPage {
  codes: Uint32Array;
  boxes: Float32Array;
  lines: Uint32Array;
}

/** El texto de las páginas `indices` de `docPtr`. */
export function pageTexts(reader: PageReader, docPtr: number, indices: number[]): PageTexts {
  const pages: PageTexts['pages'] = [];
  const packed: PackedPage[] = [];
  for (const index of indices) {
    reader.withPage(docPtr, index, (page, geo) => {
      const found = readPage(reader, page, geo);
      pages.push({ index, geometry: [geo.width, geo.height, geo.left, geo.top, geo.rotation], count: found.codes.length });
      packed.push(found);
    });
  }
  return { pages, data: pack(packed) };
}

function readPage(reader: PageReader, page: number, geo: Geometry): PackedPage {
  // Crecen al doble cuando se llenan (las cajas, siempre cuatro veces los caracteres).
  let codes = new Uint32Array(INITIAL_CHARS);
  let boxes = new Float32Array(INITIAL_CHARS * 4);
  let lines = new Uint32Array(INITIAL_CHARS);
  let count = 0;
  reader.withFloats([0, 0, 0, 0], (rect) => {
    reader.eachChar(page, (char) => {
      if (SKIPPED.has(char.code)) return;
      if (count === codes.length) [codes, boxes, lines] = [grown(codes), grown(boxes), grown(lines)];
      const loose = char.code === 0x0a ? null : reader.looseBox(char, rect);
      codes[count] = HYPHENS.has(char.code) ? HYPHEN : char.code;
      if (loose) boxes.set(fromPdf(geo, ...loose), count * 4);
      lines[count] = char.line;
      count++;
    }, { unrotated: true });
  });
  return { codes: codes.subarray(0, count), boxes: boxes.subarray(0, count * 4), lines: lines.subarray(0, count) };
}

/** Un array con el doble de sitio y lo que tenía. */
function grown<T extends Uint32Array | Float32Array>(array: T): T {
  const bigger = new (array.constructor as new (length: number) => T)(array.length * 2);
  bigger.set(array);
  return bigger;
}

function pack(pages: PackedPage[]): ArrayBuffer {
  const total = pages.reduce((sum, page) => sum + page.codes.length, 0);
  const buffer = new ArrayBuffer(total * BYTES_PER_CHAR);
  let offset = 0;
  for (const { codes, boxes, lines } of pages) {
    const count = codes.length;
    new Uint32Array(buffer, offset, count).set(codes);
    new Float32Array(buffer, offset + count * 4, count * 4).set(boxes);
    new Uint32Array(buffer, offset + count * 20, count).set(lines);
    offset += count * BYTES_PER_CHAR;
  }
  return buffer;
}
