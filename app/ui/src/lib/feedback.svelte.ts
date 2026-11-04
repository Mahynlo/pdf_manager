// Avisos flotantes y barra de estado. Cualquier módulo los muestra con toast() y
// setStatus(); App.svelte los pinta.
import { t } from '$texts';

export type Tone = 'info' | 'success' | 'warning' | 'danger';

export interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

const STATUS_IDLE = t.shell.status.idle;
const STATUS_MS = 4000;

let nextId = 0;
let statusTimer = 0;

export const feedback = $state<{ toasts: Toast[]; status: string }>({
  toasts: [],
  status: STATUS_IDLE,
});

/** Aviso flotante; `tone`: info | success | warning | danger. */
export function toast(message: string, tone: Tone = 'info', ms = 4500): void {
  const id = ++nextId;
  feedback.toasts.push({ id, message, tone });
  setTimeout(() => {
    feedback.toasts = feedback.toasts.filter((t) => t.id !== id);
  }, ms);
}

/** Mensaje temporal en la barra de estado (como QStatusBar.showMessage). */
export function setStatus(message: string): void {
  feedback.status = message;
  clearTimeout(statusTimer);
  statusTimer = window.setTimeout(() => {
    feedback.status = STATUS_IDLE;
  }, STATUS_MS);
}
