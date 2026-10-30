// Diálogos modales que se piden desde el código y devuelven una promesa (como
// QMessageBox, QInputDialog o QProgressDialog). Cada uno es un componente de
// components/ que recibe `done(valor)`: al llamarlo se cierra y la promesa se resuelve.
//
//   const ok = await confirmDialog('Eliminar', '¿Seguro?');
//   const result = await openModal(MiDialogo, { ...props });  // MiDialogo llama a done(valor)
import { mount, unmount } from 'svelte';
import ChoiceDialog from './components/ChoiceDialog.svelte';
import PasswordDialog from './components/PasswordDialog.svelte';
import ProgressDialog from './components/ProgressDialog.svelte';
import TextDialog from './components/TextDialog.svelte';

/** Monta `Component` como diálogo y resuelve lo que pase a `done()`. */
export function openModal(Component, props = {}) {
  return new Promise((resolve) => {
    const instance = mount(Component, {
      target: document.body,
      props: {
        ...props,
        done(value = null) {
          resolve(value);
          queueMicrotask(() => unmount(instance));
        },
      },
    });
  });
}

/**
 * Pregunta con varios botones. `buttons`: [{ label, value, tone?: 'primary' | 'danger' }],
 * de izquierda a derecha; el último recibe el foco. Resuelve el `value` elegido, o null con Esc.
 */
export function askChoice(title, message, buttons) {
  return openModal(ChoiceDialog, { title, message, buttons });
}

/** Pregunta Sí/No (como QMessageBox.question); resuelve true si se acepta. */
export async function confirmDialog(title, message, acceptLabel = 'Sí') {
  const choice = await askChoice(title, message, [
    { label: 'No', value: false },
    { label: acceptLabel, value: true, tone: 'primary' },
  ]);
  return choice === true;
}

/** Pide un texto; resuelve el texto o null si se cancela. Con `multiline`, Ctrl+Enter acepta. */
export function askText(title, label, initial = '', { multiline = false } = {}) {
  return openModal(TextDialog, { title, label, initial, multiline });
}

/**
 * Pide la contraseña de un PDF. `tryUnlock(pwd)` devuelve null si funcionó o el
 * mensaje de error. Resuelve true si se desbloqueó, false si se canceló.
 */
export async function askPassword(name, tryUnlock) {
  return (await openModal(PasswordDialog, { name, tryUnlock })) === true;
}

/**
 * Progreso de una tarea larga con «Cancelar». `cancelled` pasa a true si se cancela
 * (botón o Esc); `update(hecho, total, texto)` avanza la barra.
 */
export function progressDialog(title, message = '') {
  const progress = $state({ done: 0, total: 0, message, cancelled: false, closed: false });
  openModal(ProgressDialog, { title, progress }).then(() => {
    progress.cancelled = !progress.closed;
  });
  return {
    get cancelled() {
      return progress.cancelled;
    },
    update(done, total, label) {
      Object.assign(progress, { done, total });
      if (label) progress.message = label;
    },
    close() {
      progress.closed = true;
    },
  };
}
