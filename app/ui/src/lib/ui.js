// Acceso único a los avisos, la barra de estado y los diálogos, para componentes y
// para el código imperativo del visor.
export { setStatus, toast } from './feedback.svelte.js';
export { askChoice, askPassword, askText, confirmDialog, openModal, progressDialog } from './dialogs.svelte.js';
