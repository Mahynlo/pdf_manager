// Puente con el backend Python (pywebview). Es el único módulo que lo conoce: para
// otro transporte (p. ej. la versión de navegador) solo habría que cambiar este archivo.
//
//   const state = await call('merge.state');
//   const off = on('merge:progress', ({ done, total }) => ...);

const listeners = new Map();

// El backend envía eventos con window.pdfm.emit(nombre, datos) (ver app/host.py).
window.pdfm = {
  emit(event, payload) {
    for (const fn of listeners.get(event) ?? []) fn(payload);
  },
};

const ready = new Promise((resolve) => {
  if (window.pywebview?.api) resolve();
  else window.addEventListener('pywebviewready', resolve, { once: true });
});

export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

/** Llama a "servicio.metodo" del backend; rechaza con ApiError si el backend falla. */
export async function call(method, ...args) {
  await ready;
  const res = await window.pywebview.api.call(method, args);
  if (res.ok) return res.value;
  throw new ApiError(res.error.code, res.error.message);
}

/** Escucha un evento del backend; devuelve la función para dejar de escucharlo. */
export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}
