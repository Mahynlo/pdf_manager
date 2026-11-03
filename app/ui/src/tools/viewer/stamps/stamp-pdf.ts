// PDF de una página con el dibujo de un sello: lo que EmbedPDF guarda en sus bibliotecas
// (addStampToLibrary) y pega como apariencia al colocarlo. Se escribe a mano, sin PDFium ni
// Python: un sello de texto es texto vectorial con marco; uno de imagen (PNG, JPG, SVG…), la
// imagen con su transparencia.
//
//   const pdf = await textStampPdf({ text: 'PAGADO', color: '#2E7D32', font_size: 13 });
//   const pdf = await imageStampPdf(file);

/** Sello de texto: lo mismo que una leyenda (servicio `legends`). */
export interface TextStamp {
  text: string;
  color: string;
  font_size: number;
}

// Aspecto del sello de texto (el de las leyendas en Qt): marco del color del texto sobre blanco.
const TEXT = { border: 1.5, padX: 10, padY: 6, line: 1.2, minWidth: 60 };
const FONT = 'Helvetica-Bold'; // una de las 14 fuentes estándar: no hace falta incrustarla
const MEASURE_FONT = 'bold {size}px Arial'; // mismas medidas que Helvetica
// Imagen: lado mayor del sello en puntos y de la imagen en píxeles (las SVG se dibujan a este tamaño).
const IMAGE = { maxPoints: 200, maxPixels: 1200 };

// WinAnsiEncoding: Latin-1 salvo estos caracteres (0x80-0x9F); el resto no se puede escribir.
const WIN_ANSI: Record<string, number> = {
  '€': 0x80, '‚': 0x82, 'ƒ': 0x83, '„': 0x84, '…': 0x85, '†': 0x86, '‡': 0x87, 'ˆ': 0x88, '‰': 0x89,
  'Š': 0x8a, '‹': 0x8b, 'Œ': 0x8c, 'Ž': 0x8e, '‘': 0x91, '’': 0x92, '“': 0x93, '”': 0x94, '•': 0x95,
  '–': 0x96, '—': 0x97, '˜': 0x98, '™': 0x99, 'š': 0x9a, '›': 0x9b, 'œ': 0x9c, 'ž': 0x9e, 'Ÿ': 0x9f,
};

const encoder = new TextEncoder();
const ascii = (text: string) => encoder.encode(text);

/** Color `#RRGGBB` → «r g b» (0..1) para el contenido del PDF. */
function rgb(hex: string): string {
  const value = parseInt(hex.slice(1), 16);
  return [value >> 16, (value >> 8) & 0xff, value & 0xff].map((c) => (c / 255).toFixed(3)).join(' ');
}

const num = (value: number) => (Math.round(value * 100) / 100).toString();

/** Texto como cadena literal del PDF, en WinAnsi (lo que no cabe en WinAnsi pasa a «?»). */
function pdfString(text: string): string {
  let out = '(';
  for (const char of text) {
    const code = char.codePointAt(0)!;
    const byte = WIN_ANSI[char] ?? (code >= 0x20 && code <= 0xff && !(code >= 0x7f && code < 0xa0) ? code : 0x3f);
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

/** PDF de una página `width`×`height` (puntos) con `content`; `resources` y objetos extra (imágenes). */
async function onePagePdf(width: number, height: number, content: string,
                          resources: string, extra: { dict: string; stream?: Uint8Array }[] = []): Promise<ArrayBuffer> {
  // 1 catálogo, 2 páginas, 3 página, 4 contenido, 5… los extra.
  const contents = await deflate(ascii(content));
  const objects: { dict: string; stream?: Uint8Array }[] = [
    { dict: '<< /Type /Catalog /Pages 2 0 R >>' },
    { dict: '<< /Type /Pages /Kids [3 0 R] /Count 1 >>' },
    { dict: `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(width)} ${num(height)}] /Resources ${resources} /Contents 4 0 R >>` },
    { dict: '<< /Filter /FlateDecode >>', stream: contents },
    ...extra,
  ];
  const parts: Uint8Array[] = [ascii('%PDF-1.7\n%\xe2\xe3\xcf\xd3\n')];
  let length = parts[0].length;
  const offsets: number[] = [];
  const push = (part: Uint8Array) => {
    parts.push(part);
    length += part.length;
  };
  objects.forEach(({ dict, stream }, i) => {
    offsets.push(length);
    if (stream) {
      push(ascii(`${i + 1} 0 obj\n${dict.replace(/>>$/, `/Length ${stream.length} >>`)}\nstream\n`));
      push(stream);
      push(ascii('\nendstream\nendobj\n'));
    } else {
      push(ascii(`${i + 1} 0 obj\n${dict}\nendobj\n`));
    }
  });
  const xref = length;
  const rows = offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  push(ascii(`xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${rows}`
    + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`));
  const out = new Uint8Array(length);
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out.buffer;
}

/** Comprime con zlib (FlateDecode). */
async function deflate(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new CompressionStream('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Sello de texto: cada línea centrada, con marco del color del texto y fondo blanco. */
export async function textStampPdf({ text, color, font_size: size }: TextStamp): Promise<ArrayBuffer> {
  const lines = text.split('\n').map((line) => line.trimEnd());
  const context = new OffscreenCanvas(1, 1).getContext('2d')!;
  const widths = lines.map((line) => measure(context, line, size));
  const width = Math.max(TEXT.minWidth, Math.max(...widths) + 2 * TEXT.padX);
  const lineHeight = size * TEXT.line;
  const height = lines.length * lineHeight + 2 * TEXT.padY;
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
  return onePagePdf(width, height, ops.join('\n'), font);
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
  return onePagePdf(width, height, `q ${num(width)} 0 0 ${num(height)} 0 0 cm /Im1 Do Q`,
    '<< /XObject << /Im1 5 0 R >> >>', [
      { dict: `<< ${image} /ColorSpace /DeviceRGB /SMask 6 0 R >>`, stream: await deflate(color) },
      { dict: `<< ${image} /ColorSpace /DeviceGray >>`, stream: await deflate(alpha) },
    ]);
}
