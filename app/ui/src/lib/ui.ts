// Acceso único a los avisos, la barra de estado y los diálogos, para componentes y
// para el código imperativo del visor.
export { setStatus, toast } from './feedback.svelte.ts';
export type { Tone } from './feedback.svelte.ts';
export { askChoice, askPassword, askText, confirmDialog, openModal, progressDialog } from './dialogs.svelte.ts';
export type { Choice, Progress } from './dialogs.svelte.ts';
