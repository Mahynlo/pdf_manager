// Escribe a mano un PDF pequeño, sin PDFium ni Python: los sellos (viewer/stamps/stamp-pdf.ts) y
// las páginas hechas con imágenes (lib/images). Cada objeto se añade con `add` (devuelve su número)
// y cada página con `page`; `finish` da el archivo.
//
//   const pdf = new PdfWriter();
//   const image = pdf.add('<< /Type /XObject … >>', bytes);
//   pdf.page(595, 842, 'q 595 0 0 842 0 0 cm /Im1 Do Q', `<< /XObject << /Im1 ${image} 0 R >> >>`);
//   const data = await pdf.finish();

const encoder = new TextEncoder();
export const ascii = (text: string) => encoder.encode(text);

/** Número para el contenido del PDF, con dos decimales como mucho. */
export const num = (value: number) => (Math.round(value * 100) / 100).toString();

/** Comprime con zlib (FlateDecode). */
export async function deflate(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new CompressionStream('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

interface PdfObject {
  dict: string;
  stream?: Uint8Array;
}

export class PdfWriter {
  // 1 catálogo, 2 árbol de páginas; los demás, en el orden en que se añaden.
  private objects: (PdfObject | null)[] = [null, null];
  private pages: number[] = [];

  /** Añade un objeto (con `stream`, su contenido tal cual; `/Length` lo pone el escritor). Devuelve su número. */
  add(dict: string, stream?: Uint8Array): number {
    this.objects.push({ dict, stream });
    return this.objects.length;
  }

  /** Añade una página de `width`×`height` puntos con el contenido `content` (se comprime) y sus recursos. */
  async page(width: number, height: number, content: string, resources: string): Promise<void> {
    const contents = this.add('<< /Filter /FlateDecode >>', await deflate(ascii(content)));
    this.pages.push(this.add(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(width)} ${num(height)}] `
      + `/Resources ${resources} /Contents ${contents} 0 R >>`));
  }

  get pageCount(): number {
    return this.pages.length;
  }

  finish(): ArrayBuffer {
    this.objects[0] = { dict: '<< /Type /Catalog /Pages 2 0 R >>' };
    this.objects[1] = { dict: `<< /Type /Pages /Kids [${this.pages.map((n) => `${n} 0 R`).join(' ')}] /Count ${this.pages.length} >>` };
    const parts: Uint8Array[] = [ascii('%PDF-1.7\n%\xe2\xe3\xcf\xd3\n')];
    let length = parts[0].length;
    const offsets: number[] = [];
    const push = (part: Uint8Array) => {
      parts.push(part);
      length += part.length;
    };
    this.objects.forEach((object, i) => {
      const { dict, stream } = object!;
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
    const size = this.objects.length + 1;
    push(ascii(`xref\n0 ${size}\n0000000000 65535 f \n${rows}trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`));
    const out = new Uint8Array(length);
    let at = 0;
    for (const part of parts) {
      out.set(part, at);
      at += part.length;
    }
    return out.buffer;
  }
}
