// La copia del documento del visor que sale de él: a un archivo (guardar, extraer una página), a
// la impresora y a Python cuando necesita el PDF (exportar sus imágenes).
//
// El dueño del documento es EmbedPDF: la copia la saca su motor (lib/pdf-engine, `saveCopy`) sin
// el texto invisible del OCR, que solo sirve para seleccionar y buscar en el visor. Python la
// escribe tal cual al guardar. El texto que lee Python no va en una copia: ver text.ts.
import { call, upload } from '$lib/api.ts';
import { t } from '$texts';
import type { PageCanvas } from '../canvas/canvas.ts';
import { copies } from '../canvas/embed.ts';
import { pageUids } from './pages.ts';

/** Una copia ya subida, para pasársela a un servicio de Python. */
export interface Uploaded {
  url: string; // de dónde la toma Python (viewer.upload_url)
  keys: string[]; // la clave de cada página (pages.ts)
}

/** Sube `data` (un PDF, el texto de unas páginas o imágenes de página) para Python; devuelve su URL. */
export async function send(data: ArrayBuffer): Promise<string> {
  const url = await call<string>('viewer.upload_url');
  const response = await upload(url, data);
  if (!response.ok) throw new Error(t.viewer.document.uploadError(response.status));
  return url;
}

export class DocumentCopy {
  /** `commit`: escribe en el documento de EmbedPDF las anotaciones pendientes. */
  constructor(private canvas: PageCanvas, private commit: () => Promise<void>) {}

  /** El PDF tal como está en el visor. `decrypt`: sin cifrado (para imprimir). */
  async pdf({ decrypt = false } = {}): Promise<ArrayBuffer> {
    await this.commit();
    const engine = await copies();
    return engine.saveCopy(this.canvas.shownDocument(), { withoutText: this.ocrPages(), decrypt, password: this.canvas.password });
  }

  /** La página `index` como un PDF nuevo, con sus anotaciones (extraer página). */
  async page(index: number): Promise<ArrayBuffer> {
    await this.commit();
    const engine = await copies();
    return engine.extractCopy(this.canvas.shownDocument(), [index], this.ocrPages());
  }

  /** Sube a Python el PDF tal como está en el visor (ver `Uploaded`). */
  async upload(): Promise<Uploaded> {
    this.canvas.finishEditing(); // el texto que se está escribiendo también cuenta
    await this.canvas.loading;
    const keys = [...this.canvas.keys];
    return { url: await send(await this.pdf()), keys };
  }

  /** Las páginas que llevan el texto del OCR, por su posición. */
  private ocrPages(): number[] {
    return pageUids(this.canvas.keys).flatMap((uid, index) => (this.canvas.ocrPages.has(uid) ? [index] : []));
  }
}
