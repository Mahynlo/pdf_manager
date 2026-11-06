// Puente con el backend Python. Es el único módulo que sabe dónde está: en el escritorio, detrás
// de pywebview; en la versión de navegador (`vite --mode browser`), en un worker (lib/browser/).
//
//   const state = await call('merge.state');
//   const off = on('merge:progress', ({ done, total }) => ...);
//
// `call<T>()` y `on<T>()` aceptan el tipo de la respuesta o del evento; sin él es `any`.

/** Respuesta de `api.call` en Python (app/backend/rpc.py). */
type RpcResult = { ok: true; value: unknown } | { ok: false; error: { code: string; message: string } };

declare global {
  interface Window {
    pdfm: { emit(event: string, payload: unknown): void };
    pywebview?: { api: { call(method: string, args: unknown[]): Promise<RpcResult> } };
  }
}

type Listener = (payload: any) => void;

const listeners = new Map<string, Set<Listener>>();

// El backend envía eventos con window.pdfm.emit(nombre, datos) (ver app/host.py).
window.pdfm = {
  emit(event, payload) {
    for (const fn of listeners.get(event) ?? []) fn(payload);
  },
};

let browser: typeof import('./browser/client.ts') | null = null; // solo en la versión de navegador

const ready: Promise<void> = import.meta.env.MODE === 'browser'
  ? import('./browser/client.ts').then((client) => {
    browser = client;
    return client.start();
  })
  : new Promise<void>((resolve) => {
    if (window.pywebview?.api) resolve();
    else window.addEventListener('pywebviewready', () => resolve(), { once: true });
  });

export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

/** Llama a "servicio.metodo" del backend; rechaza con ApiError si el backend falla. */
export async function call<T = any>(method: string, ...args: unknown[]): Promise<T> {
  await ready;
  const res = await (browser ? browser.call(method, args) : window.pywebview!.api.call(method, args));
  if (res.ok) return res.value as T;
  throw new ApiError(res.error.code, res.error.message);
}

/** Sube `body` a una URL de subida del backend. */
export async function upload(url: string, body: ArrayBuffer): Promise<{ ok: boolean; status: number }> {
  if (!browser) return fetch(url, { method: 'POST', body });
  browser.upload(url, body);
  return { ok: true, status: 200 };
}

/** PDF soltados en la ventana. En el escritorio no hace nada: los recibe la ventana pywebview. */
export function openDropped(transfer: DataTransfer): void {
  void browser?.openDropped(transfer);
}

/** Escucha un evento del backend; devuelve la función para dejar de escucharlo. */
export function on<T = any>(event: string, fn: (payload: T) => void): () => void {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event)!.add(fn);
  return () => listeners.get(event)!.delete(fn);
}
