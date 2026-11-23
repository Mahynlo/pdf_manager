// Imágenes convertidas en páginas de PDF: las del diálogo «Imágenes a PDF» (ImagesDialog.svelte),
// que crea un documento nuevo, inserta páginas en uno abierto o rehace la página de una imagen.
//
// Cada imagen ocupa una página: `layout` decide el tamaño de la hoja y dónde va la imagen
// (`PageOptions`: tamaño, orientación, margen, encajar o rellenar) y `imagesPdf` escribe el PDF a
// mano ($lib/pdf-writer.ts), igual en el escritorio y en el navegador:
// - un JPG va tal cual (DCTDecode): sin recomprimir, sin perder calidad ni crecer. Su orientación
//   EXIF (las fotos del móvil) y el giro que elija el usuario se aplican al dibujarlo;
// - lo demás (PNG, WebP, GIF, BMP, SVG) lo dibuja la ventana y va sin pérdida (FlateDecode), con
//   su transparencia si la tiene.
//
//   const images = await loadImages(files);
//   const pdf = await imagesPdf(images.map((image) => ({ image, rotation: 0, options: DEFAULT_OPTIONS })));
// Ruta relativa: lo carga también Node en las pruebas (tests/engine_task.mjs, tarea «images»).
import { deflate, num, PdfWriter } from '../pdf-writer.ts';

// ── Opciones de página ──────────────────────────────────────────────────────
export type Paper = 'a4' | 'letter' | 'oficio' | 'legal' | 'a5' | 'a3' | 'image';
export type Orientation = 'auto' | 'portrait' | 'landscape';
export type Margin = 'none' | 'small' | 'normal' | 'wide';
export type Fit = 'contain' | 'cover';

export interface PageOptions {
  paper: Paper;
  orientation: Orientation; // con `paper: 'image'` no cuenta
  margin: Margin;
  fit: Fit; // encajar la imagen entera o rellenar la hoja (recortando lo que sobra)
}

export const DEFAULT_OPTIONS: PageOptions = { paper: 'a4', orientation: 'auto', margin: 'none', fit: 'contain' };

const MM = 72 / 25.4; // puntos por milímetro
/** Tamaño de cada hoja en puntos, en vertical. */
export const PAPERS: Record<Exclude<Paper, 'image'>, [number, number]> = {
  a4: [210 * MM, 297 * MM],
  letter: [612, 792],
  oficio: [216 * MM, 340 * MM], // el oficio de México
  legal: [612, 1008],
  a5: [148 * MM, 210 * MM],
  a3: [297 * MM, 420 * MM],
};
/** Lado mayor de la hoja «igual que la imagen»: el de un A4. */
const IMAGE_PAGE = 297 * MM;
export const MARGINS: Record<Margin, number> = { none: 0, small: 5 * MM, normal: 10 * MM, wide: 20 * MM };

/** Giro que elige el usuario, en grados en el sentido de las agujas del reloj. */
export type Rotation = 0 | 90 | 180 | 270;

/** Rectángulo en puntos del PDF: `x`, `y` desde abajo a la izquierda. */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PageLayout {
  width: number; // la hoja, en puntos
  height: number;
  image: Rect; // dónde se dibuja la imagen (ya girada)
  clip: Rect; // lo que se ve de ella: el área dentro de los márgenes
}

/** La hoja y el sitio de una imagen de `width`×`height` (ya girada; en píxeles o cualquier unidad). */
export function layout(width: number, height: number, options: PageOptions): PageLayout {
  const margin = MARGINS[options.margin];
  let page: [number, number];
  if (options.paper === 'image') {
    const scale = (IMAGE_PAGE - 2 * margin) / Math.max(width, height);
    page = [width * scale + 2 * margin, height * scale + 2 * margin];
  } else {
    const [short, long] = PAPERS[options.paper];
    const landscape = options.orientation === 'landscape' || (options.orientation === 'auto' && width > height);
    page = landscape ? [long, short] : [short, long];
  }
  const [pageWidth, pageHeight] = page;
  const clip = { x: margin, y: margin, width: pageWidth - 2 * margin, height: pageHeight - 2 * margin };
  const fit = options.fit === 'cover' ? Math.max : Math.min;
  const scale = fit(clip.width / width, clip.height / height);
  const [w, h] = [width * scale, height * scale];
  const image = { x: clip.x + (clip.width - w) / 2, y: clip.y + (clip.height - h) / 2, width: w, height: h };
  return { width: pageWidth, height: pageHeight, image, clip };
}

// ── Imágenes ────────────────────────────────────────────────────────────────
/** Una imagen elegida: se lee una vez y se codifica para el PDF la primera vez que hace falta. */
export interface SourceImage {
  name: string;
  blob: Blob;
  url: string; // para verla (miniatura, vista previa); `releaseImages` la suelta
  width: number; // tal como se ve (con la orientación EXIF aplicada), en píxeles
  height: number;
  encoded?: Promise<EncodedImage>;
}

/** Una imagen en una página: con qué giro y con qué opciones (con esto se puede rehacer la página). */
export interface ImagePage {
  image: SourceImage;
  rotation: Rotation;
  options: PageOptions;
}

/** La imagen como objeto del PDF. */
interface EncodedImage {
  dict: string; // sin /Length (lo pone el escritor) ni /SMask
  data: Uint8Array;
  mask?: { dict: string; data: Uint8Array }; // transparencia
  mirror: boolean; // orientación EXIF que hay que aplicar al dibujarla: espejo y luego giro
  turns: number; // cuartos de vuelta en el sentido de las agujas del reloj
}

const MAX_PIXELS = 6000; // lado mayor con que se dibuja una imagen que no es JPG
const SVG_PIXELS = 2400; // una SVG no tiene tamaño en píxeles: se dibuja con este lado mayor

/** Lee las imágenes de `files` (las que no se pueden leer van en `failed`). */
export async function loadImages(files: { name: string; blob: Blob }[]): Promise<{ images: SourceImage[]; failed: string[] }> {
  const images: SourceImage[] = [];
  const failed: string[] = [];
  for (const { name, blob } of files) {
    const url = URL.createObjectURL(blob);
    try {
      const element = await decoded(url);
      images.push({ name, blob, url, width: element.naturalWidth || 300, height: element.naturalHeight || 300 });
    } catch {
      URL.revokeObjectURL(url);
      failed.push(name);
    }
  }
  return { images, failed };
}

/** Suelta lo que guardan las imágenes que ya no se usan. */
export function releaseImages(images: SourceImage[]): void {
  for (const image of images) URL.revokeObjectURL(image.url);
}

async function decoded(url: string): Promise<HTMLImageElement> {
  const element = new Image();
  element.src = url;
  await element.decode();
  return element;
}

/** Tamaño de la imagen tal como queda en la página, con el giro del usuario. */
export function rotatedSize(image: SourceImage, rotation: Rotation): [number, number] {
  return rotation % 180 ? [image.height, image.width] : [image.width, image.height];
}

function encode(image: SourceImage): Promise<EncodedImage> {
  image.encoded ??= encodeImage(image).catch((err) => {
    image.encoded = undefined; // que se pueda volver a intentar
    throw err;
  });
  return image.encoded;
}

async function encodeImage(image: SourceImage): Promise<EncodedImage> {
  const bytes = new Uint8Array(await image.blob.arrayBuffer());
  const jpeg = readJpeg(bytes);
  // CMYK (4 componentes) se dibuja: muchos van invertidos (Adobe) y no siempre se sabe cuáles.
  if (jpeg && jpeg.components !== 4) {
    const space = jpeg.components === 1 ? '/DeviceGray' : '/DeviceRGB';
    const [mirror, turns] = EXIF_ORIENTATION[jpeg.orientation] ?? [false, 0];
    return {
      dict: `<< /Type /XObject /Subtype /Image /Width ${jpeg.width} /Height ${jpeg.height} /ColorSpace ${space} `
        + '/BitsPerComponent 8 /Filter /DCTDecode >>',
      data: bytes,
      mirror,
      turns,
    };
  }
  return pixelsImage(image);
}

/** La imagen dibujada por la ventana (ya orientada), sin pérdida. */
async function pixelsImage(image: SourceImage): Promise<EncodedImage> {
  const element = await decoded(image.url);
  const svg = image.blob.type === 'image/svg+xml' || image.name.toLowerCase().endsWith('.svg');
  const largest = Math.max(image.width, image.height);
  const scale = svg ? SVG_PIXELS / largest : Math.min(1, MAX_PIXELS / largest);
  const width = Math.max(1, Math.round(image.width * scale));
  const height = Math.max(1, Math.round(image.height * scale));
  const canvas = new OffscreenCanvas(width, height);
  const context = canvas.getContext('2d')!;
  context.drawImage(element, 0, 0, width, height);
  const pixels = context.getImageData(0, 0, width, height).data;
  const color = new Uint8Array(width * height * 3);
  const alpha = new Uint8Array(width * height);
  let transparent = false;
  for (let i = 0, j = 0; i < pixels.length; i += 4, j++) {
    color[j * 3] = pixels[i];
    color[j * 3 + 1] = pixels[i + 1];
    color[j * 3 + 2] = pixels[i + 2];
    alpha[j] = pixels[i + 3];
    if (pixels[i + 3] !== 255) transparent = true;
  }
  const head = `/Type /XObject /Subtype /Image /Width ${width} /Height ${height} /BitsPerComponent 8 /Filter /FlateDecode`;
  return {
    dict: `<< ${head} /ColorSpace /DeviceRGB >>`,
    data: await deflate(color),
    mask: transparent ? { dict: `<< ${head} /ColorSpace /DeviceGray >>`, data: await deflate(alpha) } : undefined,
    mirror: false,
    turns: 0,
  };
}

// ── JPG ─────────────────────────────────────────────────────────────────────
/** Orientación EXIF → [espejo, cuartos de vuelta a la derecha] para verla bien (espejo primero). */
const EXIF_ORIENTATION: Record<number, [boolean, number]> = {
  1: [false, 0], 2: [true, 0], 3: [false, 2], 4: [true, 2], 5: [true, 3], 6: [false, 1], 7: [true, 1], 8: [false, 3],
};

interface JpegInfo {
  width: number; // tal como está guardada (sin la orientación)
  height: number;
  components: number;
  orientation: number; // EXIF, 1 si no tiene
}

/** Lo que dice la cabecera de un JPG (null si no lo es o no se entiende). */
export function readJpeg(bytes: Uint8Array): JpegInfo | null {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let orientation = 1;
  let at = 2;
  while (at + 4 <= bytes.length) {
    if (bytes[at] !== 0xff) return null;
    const marker = bytes[at + 1];
    if (marker === 0xff) { // relleno
      at++;
      continue;
    }
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7)) { // sin longitud
      at += 2;
      continue;
    }
    const length = view.getUint16(at + 2);
    const start = at + 4;
    if (marker === 0xe1 && length >= 8 && text(bytes, start, 6) === 'Exif\0\0') {
      orientation = exifOrientation(view, start + 6, start + length - 2) ?? orientation;
    }
    // SOF de los JPG que entiende un lector de PDF (no los diferenciales ni los aritméticos raros)
    if ([0xc0, 0xc1, 0xc2].includes(marker)) {
      if (start + 6 > bytes.length) return null;
      return { height: view.getUint16(start + 1), width: view.getUint16(start + 3), components: bytes[start + 5], orientation };
    }
    if (marker === 0xda || (marker >= 0xc3 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc)) return null;
    at = start + length - 2;
  }
  return null;
}

const text = (bytes: Uint8Array, start: number, length: number) => String.fromCharCode(...bytes.subarray(start, start + length));

/** La etiqueta de orientación (0x0112) del TIFF que empieza en `tiff`. */
function exifOrientation(view: DataView, tiff: number, end: number): number | null {
  if (tiff + 8 > end) return null;
  const little = view.getUint16(tiff) === 0x4949; // «II»: Intel
  const u16 = (at: number) => view.getUint16(at, little);
  const ifd = tiff + view.getUint32(tiff + 4, little);
  if (ifd + 2 > end) return null;
  const count = u16(ifd);
  for (let i = 0; i < count; i++) {
    const entry = ifd + 2 + i * 12;
    if (entry + 12 > end) return null;
    if (u16(entry) === 0x0112) return u16(entry + 8);
  }
  return null;
}

// ── El PDF ──────────────────────────────────────────────────────────────────
type Matrix = [number, number, number, number, number, number];

/**
 * La matriz que dibuja la imagen (el cuadrado unidad, con su fila de arriba en y = 1) en `box`
 * tras aplicarle `mirror` y `turns` cuartos de vuelta a la derecha.
 */
export function imageMatrix(box: Rect, mirror: boolean, turns: number): Matrix {
  const map = ([u, v]: [number, number]): [number, number] => {
    let point: [number, number] = mirror ? [1 - u, v] : [u, v];
    for (let i = 0; i < ((turns % 4) + 4) % 4; i++) point = [point[1], 1 - point[0]];
    return point;
  };
  const [e, f] = map([0, 0]);
  const [a, b] = map([1, 0]).map((value, i) => value - [e, f][i]);
  const [c, d] = map([0, 1]).map((value, i) => value - [e, f][i]);
  return [a * box.width, b * box.height, c * box.width, d * box.height, box.x + e * box.width, box.y + f * box.height];
}

/**
 * El PDF con una página por imagen. `progress(i)` avisa antes de preparar cada una (codificar
 * una imagen grande tarda).
 */
export async function imagesPdf(pages: ImagePage[], progress?: (index: number) => void): Promise<ArrayBuffer> {
  const pdf = new PdfWriter();
  const written = new Map<SourceImage, number>(); // la misma imagen en varias páginas va una vez
  for (const [index, { image, rotation, options }] of pages.entries()) {
    progress?.(index);
    const encoded = await encode(image);
    let ref = written.get(image);
    if (ref === undefined) {
      const mask = encoded.mask && pdf.add(encoded.mask.dict, encoded.mask.data);
      ref = pdf.add(mask ? encoded.dict.replace(/>>$/, `/SMask ${mask} 0 R >>`) : encoded.dict, encoded.data);
      written.set(image, ref);
    }
    const [width, height] = rotatedSize(image, rotation);
    const page = layout(width, height, options);
    const { clip } = page;
    const matrix = imageMatrix(page.image, encoded.mirror, encoded.turns + rotation / 90).map(num).join(' ');
    const content = `q ${num(clip.x)} ${num(clip.y)} ${num(clip.width)} ${num(clip.height)} re W n ${matrix} cm /Im1 Do Q`;
    await pdf.page(page.width, page.height, content, `<< /XObject << /Im1 ${ref} 0 R >> >>`);
  }
  return pdf.finish();
}
