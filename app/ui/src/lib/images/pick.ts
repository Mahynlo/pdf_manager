// De dónde llegan las imágenes del diálogo «Imágenes a PDF»: el selector de archivos de la ventana
// (`pickImageFiles`: igual en WebView2 y en el navegador) o las rutas que manda Python al abrirlas
// con «Abrir» o arrastrarlas (`readImagePaths`: evento `images:open`, servicio `documents`). Y las
// opciones de página de la última vez, que recuerda cada navegador.
import { call } from '$lib/api.ts';
import { fileName } from '$lib/dom.ts';
import { DEFAULT_OPTIONS, MARGINS, PAPERS, type PageOptions } from './images.ts';

// Las que sabe dibujar la ventana (documents.py IMAGE_SUFFIXES).
const ACCEPT = '.png,.jpg,.jpeg,.webp,.bmp,.gif,.svg,image/png,image/jpeg,image/webp,image/bmp,image/gif,image/svg+xml';
const TYPES: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', bmp: 'image/bmp', gif: 'image/gif', svg: 'image/svg+xml',
};
const OPTIONS_KEY = 'images-pdf-options';

/** Elige imágenes con el selector de la ventana; lista vacía si se cancela. */
export function pickImageFiles(): Promise<{ name: string; blob: Blob }[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = ACCEPT;
    input.multiple = true;
    input.addEventListener('change', () => resolve([...input.files!].map((file) => ({ name: file.name, blob: file }))));
    input.addEventListener('cancel', () => resolve([]));
    input.click();
  });
}

/** Lee las imágenes `paths` (de `images:open`): Python da una URL de un solo uso por cada una. */
export async function readImagePaths(paths: string[]): Promise<{ files: { name: string; blob: Blob }[]; failed: string[] }> {
  const files: { name: string; blob: Blob }[] = [];
  const failed: string[] = [];
  for (const path of paths) {
    const name = fileName(path);
    try {
      const response = await fetch(await call<string>('documents.image_url', path));
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.arrayBuffer();
      const type = TYPES[name.split('.').pop()!.toLowerCase()] ?? '';
      files.push({ name, blob: new Blob([data], { type }) });
    } catch {
      failed.push(name);
    }
  }
  return { files, failed };
}

/** Las opciones de página de la última vez (o las de siempre). */
export function rememberedOptions(): PageOptions {
  try {
    const saved = JSON.parse(localStorage.getItem(OPTIONS_KEY) ?? 'null') as Partial<PageOptions> | null;
    if (!saved) return { ...DEFAULT_OPTIONS };
    return {
      paper: saved.paper && (saved.paper === 'image' || saved.paper in PAPERS) ? saved.paper : DEFAULT_OPTIONS.paper,
      orientation: ['auto', 'portrait', 'landscape'].includes(saved.orientation ?? '') ? saved.orientation! : DEFAULT_OPTIONS.orientation,
      margin: saved.margin && saved.margin in MARGINS ? saved.margin : DEFAULT_OPTIONS.margin,
      fit: saved.fit === 'cover' ? 'cover' : 'contain',
    };
  } catch {
    return { ...DEFAULT_OPTIONS };
  }
}

export function rememberOptions(options: PageOptions): void {
  try {
    localStorage.setItem(OPTIONS_KEY, JSON.stringify(options));
  } catch {
    // sin almacenamiento (ventana privada): la próxima vez, las de siempre
  }
}
