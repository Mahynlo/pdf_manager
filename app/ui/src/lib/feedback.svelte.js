// Avisos flotantes y barra de estado. Cualquier módulo los muestra con toast() y
// setStatus(); App.svelte los pinta.

const STATUS_IDLE = 'Listo • Extraer PDFs';
const STATUS_MS = 4000;

let nextId = 0;
let statusTimer = 0;

export const feedback = $state({
  toasts: [], // [{ id, message, tone }]
  status: STATUS_IDLE,
});

/** Aviso flotante; `tone`: info | success | warning | danger. */
export function toast(message, tone = 'info', ms = 4500) {
  const id = ++nextId;
  feedback.toasts.push({ id, message, tone });
  setTimeout(() => {
    feedback.toasts = feedback.toasts.filter((t) => t.id !== id);
  }, ms);
}

/** Mensaje temporal en la barra de estado (como QStatusBar.showMessage). */
export function setStatus(message) {
  feedback.status = message;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    feedback.status = STATUS_IDLE;
  }, STATUS_MS);
}
