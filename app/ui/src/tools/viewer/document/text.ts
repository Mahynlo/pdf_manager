// El texto del documento del visor para Python: su capa de texto en orden de lectura (asistente IA,
// panel del OCR, exportar texto) y la búsqueda de la censura trabajan con él. Python no tiene el
// documento: recibe la clave de cada página (`viewer.set_pages`) y el texto de las que aún no
// tiene (`viewer.add_texts`), que saca el motor de la app (lib/pdf-engine/page-text.ts).
//
// El texto de una página no cambia con sus anotaciones ni al moverla (la clave la sigue), así que
// cada versión de una página se extrae una vez.
import { call } from '$lib/api.ts';
import type { PageCanvas } from '../canvas/canvas.ts';
import { reading } from '../canvas/embed.ts';
import { send } from './copy.ts';

export class DocumentText {
  private complete: string | null = null; // las claves con las que Python ya tiene todo el texto

  constructor(private canvas: PageCanvas, private docId: number) {}

  /**
   * Python recibe las páginas como están ahora y el texto de `pages` (sin ellas, de todas) que
   * aún no tiene. Llamarlo antes de lo que lee el texto en Python.
   */
  async sync(pages: number[] | null = null): Promise<void> {
    await this.canvas.loading;
    if (!this.canvas.shown) return;
    const keys = [...this.canvas.keys];
    const signature = keys.join(',');
    if (this.complete === signature) return;
    const { missing } = await call<{ missing: number[] }>('viewer.set_pages', this.docId, keys);
    const wanted = pages ? missing.filter((index) => pages.includes(index)) : missing;
    if (wanted.length) {
      const texts = await (await reading()).pageTexts(this.canvas.shownDocument(), wanted);
      await call('viewer.add_texts', this.docId, await send(texts.data), texts.pages);
    }
    this.complete = wanted.length === missing.length ? signature : null;
  }

  /** Cambió el contenido de unas páginas (la censura): Python tiene que recibir su texto nuevo. */
  changed(): void {
    this.complete = null;
  }
}
