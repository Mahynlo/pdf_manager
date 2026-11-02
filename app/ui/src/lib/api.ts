// Puente con el backend Python (pywebview). Es el único módulo que lo conoce: para
// otro transporte (p. ej. la versión de navegador) solo habría que cambiar este archivo.
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

const ready = new Promise<void>((resolve) => {
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
  const res = await window.pywebview!.api.call(method, args);
  if (res.ok) return res.value as T;
  throw new ApiError(res.error.code, res.error.message);
}

/** Escucha un evento del backend; devuelve la función para dejar de escucharlo. */
export function on<T = any>(event: string, fn: (payload: T) => void): () => void {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event)!.add(fn);
  return () => listeners.get(event)!.delete(fn);
}
