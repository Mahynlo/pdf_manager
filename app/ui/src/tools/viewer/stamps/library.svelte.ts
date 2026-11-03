// Bibliotecas de sellos de EmbedPDF (plugin-stamp), una sola para toda la app como el registro.
// Todos los sellos se colocan igual (clic en el sello y clic en la página, con su vista previa).
// Los estándar y los propios son anotaciones de sello con su dibujo (un PDF de una página por
// sello); los de texto, texto libre editable (Annotations.textStamp). Hay tres clases:
//
// - **Estándar** (standard.ts): Aprobado, Borrador, Confidencial… de solo lectura.
// - **De texto:** los sellos rápidos (CONFIDENCIAL, APROBADO…) y las leyendas guardadas del
//   servicio `legends`, el almacén que comparten Qt y Flet. En la página son texto libre; su
//   miniatura se genera al vuelo (stamp-pdf.ts) en una biblioteca que solo vive en memoria.
// - **Propios:** los que crea el usuario desde una imagen (PNG, JPG, SVG…) o desde anotaciones
//   de la página. Python guarda la biblioteca (servicio `stamps`).
import { PdfAnnotationName } from '@embedpdf/models';
import type { StampCapability, StampDefinition, StampLibrary, StampPlugin } from '@embedpdf/plugin-stamp';
import { call } from '$lib/api.ts';
import { toast } from '$lib/ui.ts';
import { t } from '$texts';
import type { Annot } from '../annotations/annotations.ts';
import { registry } from '../canvas/embed.ts';
import { imageStampPdf, textStampPdf, type TextStamp } from './stamp-pdf.ts';
import { STANDARD } from './standard.ts';

export const TEXT = 'text';
export const CUSTOM = 'custom';
export const DEFAULT_COLOR = '#D32F2F';
export const DEFAULT_SIZE = 13;
const THUMB_WIDTH = 120; // px de la miniatura en el panel

const T = t.viewer.stamps;

/** Leyenda guardada (servicio `legends`). */
export interface Legend extends TextStamp {
  id: string;
  name: string;
}

/** Sello del panel. Los de texto llevan `text` (y `legendId` si es una leyenda guardada). */
export interface StampItem {
  key: string;
  name: string;
  library: string;
  stamp: StampDefinition;
  thumb: string | null;
  text?: TextStamp;
  legendId?: string;
}

const textKey = ({ text, color, font_size }: TextStamp) => `${text}\u0000${color.toUpperCase()}\u0000${font_size}`;

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function fromBase64(text: string): ArrayBuffer {
  return Uint8Array.from(atob(text), (char) => char.charCodeAt(0)).buffer;
}

class StampLibraries {
  standard = $state.raw<StampItem[]>([]);
  text = $state.raw<StampItem[]>([]);
  custom = $state.raw<StampItem[]>([]);
  loaded = $state(false);
  #ready: Promise<StampCapability> | null = null;
  #queue: Promise<unknown> = Promise.resolve(); // un cambio de bibliotecas detrás de otro
  #texts = new Map<string, StampDefinition>(); // sello de texto → su página en la biblioteca TEXT
  #thumbs = new Map<string, string>(); // `biblioteca:id` → URL de la miniatura

  /** El complemento con las bibliotecas cargadas (la de texto vacía; la propia, la guardada). */
  ready(): Promise<StampCapability> {
    this.#ready ??= (async () => {
      const stamps = (await registry()).getPlugin<StampPlugin>('stamp')!.provides();
      await stamps.createNewLibrary(T.textLibrary, { id: TEXT }).toPromise();
      const saved = await call<{ pdf: string; stamps: StampDefinition[] } | null>('stamps.library').catch(() => null);
      try {
        if (!saved) throw new Error('sin biblioteca');
        await stamps.loadLibrary({ id: CUSTOM, name: T.customLibrary, pdf: fromBase64(saved.pdf), stamps: saved.stamps }).toPromise();
      } catch (err) {
        if (saved) toast(T.loadError, 'danger');
        await stamps.createNewLibrary(T.customLibrary, { id: CUSTOM }).toPromise();
      }
      return stamps;
    })();
    return this.#ready;
  }

  /** Ejecuta `fn` cuando acaben los cambios anteriores (los sellos de texto no se generan dos veces). */
  #run<R>(fn: () => Promise<R>): Promise<R> {
    const next = this.#queue.then(fn, fn);
    this.#queue = next.catch(() => {});
    return next;
  }

  /** Vuelve a leer las tres bibliotecas para el panel (y las leyendas del servicio). */
  refresh(): Promise<void> {
    return this.#run(async () => {
      const stamps = await this.ready();
      const library = (id: string) => stamps.getLibraries().find((item) => item.id === id);
      this.standard = await this.#items(stamps, library(STANDARD));
      this.custom = await this.#items(stamps, library(CUSTOM));
      const [menu, legends] = await Promise.all([
        call<{ stamps: { text: string; color: string }[] }>('legends.menu'),
        call<Legend[]>('legends.all'),
      ]);
      const texts: { name: string; text: TextStamp; legendId?: string }[] = [
        ...menu.stamps.map(({ text, color }) => ({ name: text, text: { text, color, font_size: DEFAULT_SIZE } })),
        ...legends.map((legend) => ({ name: legend.name, text: legend, legendId: legend.id })),
      ];
      const items: StampItem[] = [];
      for (const { name, text, legendId } of texts) {
        const stamp = await this.#textStamp(stamps, text);
        items.push({
          key: legendId ?? textKey(text), name, library: TEXT, stamp, text, legendId,
          thumb: await this.#thumb(stamps, TEXT, stamp),
        });
      }
      this.text = items;
      this.loaded = true;
    }).catch((err) => {
      console.error(err);
      toast(T.loadError, 'danger');
    });
  }

  async #items(stamps: StampCapability, library: StampLibrary | undefined): Promise<StampItem[]> {
    if (!library) return [];
    const items: StampItem[] = [];
    for (const stamp of library.stamps) {
      items.push({
        key: `${library.id}:${stamp.id}`, name: stamp.subject, library: library.id, stamp,
        thumb: await this.#thumb(stamps, library.id, stamp),
      });
    }
    return items;
  }

  async #thumb(stamps: StampCapability, library: string, stamp: StampDefinition): Promise<string | null> {
    const key = `${library}:${stamp.id}`;
    if (!this.#thumbs.has(key)) {
      try {
        const blob = await stamps.renderStamp(library, stamp.pageIndex, THUMB_WIDTH, devicePixelRatio).toPromise();
        this.#thumbs.set(key, URL.createObjectURL(blob));
      } catch {
        return null;
      }
    }
    return this.#thumbs.get(key)!;
  }

  /** El sello de texto en la biblioteca TEXT (generado la primera vez que se pide). */
  async #textStamp(stamps: StampCapability, text: TextStamp): Promise<StampDefinition> {
    const key = textKey(text);
    let stamp = this.#texts.get(key);
    if (!stamp) {
      const pdf = await textStampPdf(text);
      await stamps.addStampToLibrary(TEXT, { name: PdfAnnotationName.Custom, subject: text.text }, pdf).toPromise();
      stamp = stamps.getLibraries().find((item) => item.id === TEXT)!.stamps.at(-1)!;
      this.#texts.set(key, stamp);
    }
    return stamp;
  }

  // ── Colocar ────────────────────────────────────────────────────────────
  /** El siguiente clic en una página de `documentId` coloca el sello (estándar o propio). */
  async place(documentId: string, item: StampItem): Promise<void> {
    const stamps = await this.ready();
    await stamps.forDocument(documentId).activateStampPlacement(item.library, item.stamp).toPromise();
  }

  // ── Sellos propios ─────────────────────────────────────────────────────
  /** Sello propio con el dibujo de `annotations` (de una misma página de `documentId`). */
  addFromAnnotations(documentId: string, annotations: Annot[], name: string): Promise<void> {
    return this.#change(async (stamps) => {
      const stamp = { name: PdfAnnotationName.Custom, subject: name };
      await stamps.forDocument(documentId).createStampFromAnnotations(annotations, stamp, CUSTOM).toPromise();
    });
  }

  /** Sello propio con una imagen (PNG, JPG, WebP, SVG…). */
  addFromImage(file: Blob, name: string): Promise<void> {
    return this.#change(async (stamps) => {
      const stamp = { name: PdfAnnotationName.Image, subject: name };
      await stamps.addStampToLibrary(CUSTOM, stamp, await imageStampPdf(file)).toPromise();
    });
  }

  /** Quita un sello propio o una leyenda guardada (los estándar y los rápidos no se quitan). */
  async remove(item: StampItem): Promise<void> {
    if (item.legendId) {
      await call('legends.delete', item.legendId);
      return this.refresh();
    }
    if (item.library !== CUSTOM) return;
    await this.#change((stamps) => stamps.removeStampFromLibrary(CUSTOM, item.stamp.id).toPromise());
    const thumb = this.#thumbs.get(item.key); // la clave de la miniatura es la del sello
    if (thumb) URL.revokeObjectURL(thumb);
    this.#thumbs.delete(item.key);
  }

  /** Cambia la biblioteca propia, la guarda en Python y rehace la lista del panel. */
  async #change(fn: (stamps: StampCapability) => Promise<void>): Promise<void> {
    await this.#run(async () => {
      const stamps = await this.ready();
      await fn(stamps);
      const library = await stamps.exportLibrary(CUSTOM).toPromise();
      const pdf = library.stamps.length ? toBase64(library.pdf) : null;
      await call('stamps.save_library', pdf, library.stamps);
    });
    await this.refresh();
  }
}

export const stampLibraries = new StampLibraries();
