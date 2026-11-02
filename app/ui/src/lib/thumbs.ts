// Miniaturas bajo demanda: solo se piden al backend las que llegan a verse,
// agrupadas por documento, y se guardan en una caché acotada. La usan Combinar y
// el visor, cada uno con su función `fetch(id, páginas) -> { página: url }`; con urls
// blob: (PDFium), `release(url)` las libera al salir de la caché.
//
// `variant` distingue versiones de una misma página (p. ej. el giro en Combinar):
// al cambiar, la miniatura se vuelve a pedir.
//
//   const thumbs = new ThumbLoader((id, pages) => call('merge.thumbnails', id, pages));
//   <img use:thumb={[thumbs, id, página, variante]} alt="">

const MAX_CACHED = 600; // ~15 KB por miniatura JPEG → ~9 MB como máximo
const BATCH = 24; // páginas por llamada al backend

/** Pide las miniaturas de `pages` del documento `id`: { página: url }. */
export type ThumbFetch = (id: number, pages: number[]) => Promise<Record<string, string>>;

export class ThumbLoader {
  fetch: ThumbFetch;
  release: (url: string) => void;
  images = new Set<HTMLImageElement>(); // <img> enlazadas (se quitan al desmontarse)
  cache = new Map<string, string>(); // "id:página:variante" -> data URL (orden de inserción = LRU)
  pending = new Map<string, Set<number>>(); // "id:variante" -> Set(páginas)
  timer = 0;
  observer: IntersectionObserver;

  constructor(fetch: ThumbFetch, { release = (_url: string) => {} } = {}) {
    this.fetch = fetch;
    this.release = release;
    this.observer = new IntersectionObserver((entries) => this._onVisible(entries), { rootMargin: '300px' });
  }

  /** Asocia un <img> a una página; se rellena al entrar en pantalla. */
  bind(img: HTMLImageElement, id: number, page: number, variant: number | string = 0): void {
    const key = `${id}:${page}:${variant}`;
    this.images.add(img);
    if (img.dataset.thumb === key) return;
    // Otra variante de la misma página (p. ej. cambiaron sus anotaciones): se sigue viendo la
    // anterior hasta que llega la nueva, sin parpadeo.
    const samePage = img.dataset.thumb?.startsWith(`${id}:${page}:`);
    img.dataset.thumb = key;
    const url = this._get(key);
    if (url) {
      img.src = url;
      this.observer.unobserve(img);
    } else {
      if (!samePage) img.removeAttribute('src');
      this.observer.observe(img);
    }
  }

  unbind(img: HTMLImageElement): void {
    this.images.delete(img);
    this.observer.unobserve(img);
  }

  /** Olvida las miniaturas de `id` (p. ej. al cambiar sus páginas). */
  forget(id: number): void {
    for (const [key, url] of [...this.cache]) {
      if (!key.startsWith(`${id}:`)) continue;
      this.cache.delete(key);
      this.release(url);
    }
  }

  disconnect(): void {
    this.observer.disconnect();
    for (const url of this.cache.values()) this.release(url);
    this.cache.clear();
    clearTimeout(this.timer);
  }

  _onVisible(entries: IntersectionObserverEntry[]): void {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      this.observer.unobserve(entry.target);
      const [id, page, variant] = (entry.target as HTMLElement).dataset.thumb!.split(':').map(Number);
      const group = `${id}:${variant}`;
      if (!this.pending.has(group)) this.pending.set(group, new Set());
      this.pending.get(group)!.add(page);
    }
    clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this._flush(), 30);
  }

  async _flush(): Promise<void> {
    const groups = [...this.pending];
    this.pending.clear();
    for (const [group, pageSet] of groups) {
      const [id, variant] = group.split(':').map(Number);
      const pages = [...pageSet];
      for (let i = 0; i < pages.length; i += BATCH) {
        let result: Record<string, string>;
        try {
          result = await this.fetch(id, pages.slice(i, i + BATCH));
        } catch {
          break; // el documento ya no está (se quitó o se cerró)
        }
        for (const [page, url] of Object.entries(result)) {
          const key = `${id}:${page}:${variant}`;
          this._put(key, url);
          for (const img of this.images) if (img.dataset.thumb === key) img.src = url;
        }
      }
    }
  }

  _get(key: string): string | undefined {
    const url = this.cache.get(key);
    if (url) {
      this.cache.delete(key);
      this.cache.set(key, url);
    }
    return url;
  }

  _put(key: string, url: string): void {
    // Las otras variantes de la misma página ya no se verán (p. ej. cambiaron sus anotaciones).
    const page = key.slice(0, key.lastIndexOf(':') + 1);
    for (const [other, old] of this.cache) {
      if (other !== key && other.startsWith(page)) {
        this.cache.delete(other);
        this.release(old);
      }
    }
    this.cache.set(key, url);
    if (this.cache.size <= MAX_CACHED) return;
    const [oldest, old] = this.cache.entries().next().value!;
    this.cache.delete(oldest);
    this.release(old);
  }
}

/** Argumentos de la acción `thumb`: [cargador, documento, página, variante?]. */
export type ThumbArgs = [ThumbLoader, number, number, (number | string)?];

/** Acción de Svelte para una miniatura: `<img use:thumb={[loader, id, página, variante]} alt="">`. */
export function thumb(img: HTMLImageElement, args: ThumbArgs) {
  const bind = ([loader, ...rest]: ThumbArgs) => loader.bind(img, ...rest);
  bind(args);
  return { update: bind, destroy: () => args[0].unbind(img) };
}
