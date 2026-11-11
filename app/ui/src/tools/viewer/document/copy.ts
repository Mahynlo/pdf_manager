// La copia del documento del visor que sale de él: a Python (lo que hace con el documento al día:
// guardarlo, censurar, OCR, IA…), a un archivo (extraer una página) y a la impresora.
//
// El dueño del documento es EmbedPDF: la copia la saca su motor (lib/pdf-engine, `saveCopy`) sin
// el texto invisible del OCR, que solo sirve para seleccionar y buscar en el visor. Python la
// escribe tal cual al guardar.
//
// Lleva la cuenta de los cambios (anotaciones y páginas) que Python aún no tiene: `sync` solo
// sube la copia cuando hace falta.
import { call, upload } from '$lib/api.ts';
import { t } from '$texts';
import type { PageCanvas } from '../canvas/canvas.ts';
import { copies } from '../canvas/embed.ts';
import { pageUids } from './pages.ts';

/** Una copia ya subida, para pasársela a un servicio de Python. */
export interface Uploaded {
  url: string; // de dónde la toma Python (viewer.upload_url)
  uids: number[]; // el `uid` de cada página (pages.ts)
  /** Python ya tiene esta versión como su documento (sync, guardar). */
  adopted(): void;
}

export class DocumentCopy {
  private version = 0; // cambios hechos en el documento a la vista
  private synced = 0; // `version` que ya tiene Python

  /** `commit`: escribe en el documento de EmbedPDF las anotaciones pendientes. */
  constructor(private canvas: PageCanvas, private docId: number, private commit: () => Promise<void>) {}

  /** Cambió el documento a la vista (anotaciones o páginas): Python aún no lo tiene. */
  changed(): void {
    this.version++;
  }

  /** El lienzo puso a la vista otra versión del documento, que viene de Python: ya la tiene. */
  shown(): void {
    this.version = 0;
    this.synced = 0;
  }

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
    await this.canvas.loading; // la copia tiene que ser de la versión que tiene Python
    const documentId = this.canvas.shown;
    const version = this.version;
    const url = await this.send(await this.pdf());
    return {
      url,
      uids: pageUids(this.canvas.keys),
      adopted: () => {
        if (documentId === this.canvas.shown) this.synced = Math.max(this.synced, version);
      },
    };
  }

  /** Sube `data` (un PDF) para un servicio de Python; devuelve su URL. */
  async send(data: ArrayBuffer): Promise<string> {
    const url = await call<string>('viewer.upload_url');
    const response = await upload(url, data);
    if (!response.ok) throw new Error(t.viewer.document.uploadError(response.status));
    return url;
  }

  /**
   * Pasa a Python el documento si cambió desde la última vez: la copia pasa a ser su documento.
   * Llamarlo antes de todo lo que lee el documento en Python. Resuelve `{ modified }`, o null si
   * no hacía falta.
   */
  async sync(): Promise<{ modified: boolean } | null> {
    this.canvas.finishEditing();
    await this.canvas.loading;
    if (!this.canvas.shown || this.version === this.synced) return null;
    const copy = await this.upload();
    const result = await call<{ modified: boolean }>('viewer.sync_annotations', this.docId, copy.url, copy.uids);
    copy.adopted();
    return result;
  }

  // ── Auxiliares ─────────────────────────────────────────────────────────
  /** Las páginas que llevan el texto del OCR, por su posición. */
  private ocrPages(): number[] {
    return pageUids(this.canvas.keys).flatMap((uid, index) => (this.canvas.ocrPages.has(uid) ? [index] : []));
  }
}
