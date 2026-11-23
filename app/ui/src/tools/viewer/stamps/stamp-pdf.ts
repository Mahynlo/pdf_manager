// PDF de una página con el dibujo de un sello: lo que EmbedPDF guarda en sus bibliotecas
// (addStampToLibrary) y pega como apariencia al colocarlo. Se escribe a mano, sin PDFium ni
// Python: un sello de texto es texto vectorial con marco (la miniatura del panel: en la página
// es texto libre, editable; ver `textStampSize`); uno de imagen (PNG, JPG, SVG…), la imagen con
// su transparencia. El PDF lo escribe $lib/pdf-writer.ts.
//
//   const pdf = await textStampPdf({ text: 'PAGADO', color: '#2E7D32', font_size: 13 });
//   const pdf = await imageStampPdf(file);

import { deflate, num, PdfWriter } from '$lib/pdf-writer.ts';
import { standardFontText, winAnsiCode } from '$lib/standard-font.ts';

/** Sello de texto: lo mismo que una leyenda (servicio `legends`). */
export interface TextStamp {
  text: string;
  color: string;
  font_size: number;
}

// Aspecto del sello de texto (el de las leyendas en Qt): marco del color del texto sobre blanco.
export const TEXT_STAMP = { border: 1.5, padX: 10, padY: 6, line: 1.2, minWidth: 60 };
const TEXT = TEXT_STAMP;
const FONT = 'Helvetica-Bold'; // una de las 14 fuentes estándar: no hace falta incrustarla
const MEASURE_FONT = 'bold {size}px Arial'; // mismas medidas que Helvetica
// Imagen: lado mayor del sello en puntos y de la imagen en píxeles (las SVG se dibujan a este tamaño).
const IMAGE = { maxPoints: 200, maxPixels: 1200 };

/** Color `#RRGGBB` → «r g b» (0..1) para el contenido del PDF. */
function rgb(hex: string): string {
  const value = parseInt(hex.slice(1), 16);
  return [value >> 16, (value >> 8) & 0xff, value & 0xff].map((c) => (c / 255).toFixed(3)).join(' ');
}

/** Texto como cadena literal del PDF, en WinAnsi (lo que no cabe se quita antes: `standardFontText`). */
function pdfString(text: string): string {
  let out = '(';
  for (const char of text) {
    const byte = winAnsiCode(char) ?? 0x3f;
    if (byte === 0x28 || byte === 0x29 || byte === 0x5c) out += '\\' + String.fromCharCode(byte);
    else if (byte < 0x80) out += String.fromCharCode(byte);
    else out += '\\' + byte.toString(8).padStart(3, '0');
  }
  return out + ')';
}

/** Ancho de una línea en puntos con la fuente del sello. */
function measure(context: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, text: string, size: number): number {
  context.font = MEASURE_FONT.replace('{size}', String(size));
  return context.measureText(text).width;
}

/** PDF de una página `width`×`height` (puntos) con `content` y `resources`. */
async function onePagePdf(pdf: PdfWriter, width: number, height: number, content: string, resources: string): Promise<ArrayBuffer> {
  await pdf.page(width, height, content, resources);
  return pdf.finish();
}

/**
 * Tamaño en puntos del sello de texto (y el ancho de cada línea): lo usan su miniatura, la vista
 * previa al colocarlo y el texto libre que se crea en la página, así miden lo mismo.
 */
export function textStampSize({ text, font_size: size }: TextStamp): { width: number; height: number; lines: string[]; widths: number[] } {
  const lines = standardFontText(text).text.split('\n').map((line) => line.trimEnd());
  const context = new OffscreenCanvas(1, 1).getContext('2d')!;
  const widths = lines.map((line) => measure(context, line, size));
  const width = Math.max(TEXT.minWidth, Math.max(...widths) + 2 * TEXT.padX);
  return { width, height: lines.length * size * TEXT.line + 2 * TEXT.padY, lines, widths };
}

/** Sello de texto: cada línea centrada, con marco del color del texto y fondo blanco. */
export async function textStampPdf(stamp: TextStamp): Promise<ArrayBuffer> {
  const { color, font_size: size } = stamp;
  const { width, height, lines, widths } = textStampSize(stamp);
  const lineHeight = size * TEXT.line;
  const inset = TEXT.border / 2;
  const color_ = rgb(color);
  const ops = [
    `1 1 1 rg 0 0 ${num(width)} ${num(height)} re f`,
    `${color_} RG ${TEXT.border} w ${num(inset)} ${num(inset)} ${num(width - TEXT.border)} ${num(height - TEXT.border)} re S`,
    `BT /F1 ${size} Tf ${color_} rg`,
  ];
  // Línea base de cada línea: centrada en su renglón (Helvetica: ~0.72 del tamaño sobre la base).
  lines.forEach((line, i) => {
    const x = (width - widths[i]) / 2;
    const y = height - TEXT.padY - i * lineHeight - (lineHeight + size * 0.72) / 2 + size * 0.06;
    ops.push(`1 0 0 1 ${num(x)} ${num(y)} Tm ${pdfString(line)} Tj`);
  });
  ops.push('ET');
  const font = `<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /${FONT} /Encoding /WinAnsiEncoding >> >> >>`;
  return onePagePdf(new PdfWriter(), width, height, ops.join('\n'), font);
}

/**
 * Dibuja la imagen (PNG, JPG, WebP, SVG…) en un lienzo de como mucho `IMAGE.maxPixels` de lado.
 * También la usan las firmas desde imagen (PDFium no sabe pintar una SVG).
 */
export async function rasterize(file: Blob): Promise<OffscreenCanvas> {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    // Una SVG sin tamaño propio se dibuja a 300 px, el tamaño de una imagen sin dimensiones.
    const w0 = image.naturalWidth || 300;
    const h0 = image.naturalHeight || 300;
    const scale = Math.min(IMAGE.maxPixels / Math.max(w0, h0), file.type === 'image/svg+xml' ? Infinity : 1);
    const canvas = new OffscreenCanvas(Math.max(1, Math.round(w0 * scale)), Math.max(1, Math.round(h0 * scale)));
    canvas.getContext('2d')!.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Sello de imagen: la imagen con su transparencia, de como mucho `IMAGE.maxPoints` de lado. */
export async function imageStampPdf(file: Blob): Promise<ArrayBuffer> {
  const canvas = await rasterize(file);
  const { width: pw, height: ph } = canvas;
  const pixels = canvas.getContext('2d')!.getImageData(0, 0, pw, ph).data;
  const color = new Uint8Array(pw * ph * 3);
  const alpha = new Uint8Array(pw * ph);
  for (let i = 0, j = 0; i < pixels.length; i += 4, j++) {
    color.set(pixels.subarray(i, i + 3), j * 3);
    alpha[j] = pixels[i + 3];
  }
  const scale = IMAGE.maxPoints / Math.max(pw, ph);
  const [width, height] = [pw * scale, ph * scale];
  const image = `/Type /XObject /Subtype /Image /Width ${pw} /Height ${ph} /BitsPerComponent 8 /Filter /FlateDecode`;
  const pdf = new PdfWriter();
  const mask = pdf.add(`<< ${image} /ColorSpace /DeviceGray >>`, await deflate(alpha));
  const picture = pdf.add(`<< ${image} /ColorSpace /DeviceRGB /SMask ${mask} 0 R >>`, await deflate(color));
  return onePagePdf(pdf, width, height, `q ${num(width)} 0 0 ${num(height)} 0 0 cm /Im1 Do Q`,
    `<< /XObject << /Im1 ${picture} 0 R >> >>`);
}
