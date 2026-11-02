// Diálogos modales que se piden desde el código y devuelven una promesa (como
// QMessageBox, QInputDialog o QProgressDialog). Cada uno es un componente de
// components/ que recibe `done(valor)`: al llamarlo se cierra y la promesa se resuelve.
//
//   const ok = await confirmDialog('Eliminar', '¿Seguro?');
//   const result = await openModal(MiDialogo, { ...props });  // MiDialogo llama a done(valor)
import { mount, unmount, type Component } from 'svelte';
import ChoiceDialog from './components/ChoiceDialog.svelte';
import PasswordDialog from './components/PasswordDialog.svelte';
import ProgressDialog from './components/ProgressDialog.svelte';
import TextDialog from './components/TextDialog.svelte';
import { t } from '$texts';

/** Botón de askChoice(). */
export interface Choice<T = unknown> {
  label: string;
  value: T;
  tone?: 'primary' | 'danger';
}

/** Estado de progressDialog() que pinta ProgressDialog.svelte. */
export interface Progress {
  done: number;
  total: number;
  message: string;
  cancelled: boolean;
  closed: boolean;
}

/** Monta `Component` como diálogo y resuelve lo que pase a `done()`. */
export function openModal<T = any>(Component: Component<any>, props: Record<string, unknown> = {}): Promise<T | null> {
  return new Promise((resolve) => {
    const instance = mount(Component, {
      target: document.body,
      props: {
        ...props,
        done(value: T | null = null) {
          resolve(value);
          queueMicrotask(() => unmount(instance));
        },
      },
    });
  });
}

/**
 * Pregunta con varios botones, de izquierda a derecha; el último recibe el foco. Resuelve el
 * `value` elegido, o null con Esc.
 */
export function askChoice<T>(title: string, message: string, buttons: Choice<T>[]): Promise<T | null> {
  return openModal<T>(ChoiceDialog, { title, message, buttons });
}

/** Pregunta Sí/No (como QMessageBox.question); resuelve true si se acepta. */
export async function confirmDialog(title: string, message: string, acceptLabel = t.common.yes): Promise<boolean> {
  const choice = await askChoice(title, message, [
    { label: t.common.no, value: false },
    { label: acceptLabel, value: true, tone: 'primary' },
  ]);
  return choice === true;
}

/** Pide un texto; resuelve el texto o null si se cancela. Con `multiline`, Ctrl+Enter acepta. */
export function askText(title: string, label: string, initial = '', { multiline = false } = {}): Promise<string | null> {
  return openModal<string>(TextDialog, { title, label, initial, multiline });
}

/**
 * Pide la contraseña de un PDF. `tryUnlock(pwd)` devuelve null si funcionó o el
 * mensaje de error. Resuelve true si se desbloqueó, false si se canceló.
 */
export async function askPassword(name: string, tryUnlock: (password: string) => Promise<string | null>): Promise<boolean> {
  return (await openModal<boolean>(PasswordDialog, { name, tryUnlock })) === true;
}

/**
 * Progreso de una tarea larga con «Cancelar». `cancelled` pasa a true si se cancela
 * (botón o Esc); `update(hecho, total, texto)` avanza la barra.
 */
export function progressDialog(title: string, message = '') {
  const progress = $state<Progress>({ done: 0, total: 0, message, cancelled: false, closed: false });
  openModal(ProgressDialog, { title, progress }).then(() => {
    progress.cancelled = !progress.closed;
  });
  return {
    get cancelled(): boolean {
      return progress.cancelled;
    },
    update(done: number, total: number, label?: string): void {
      Object.assign(progress, { done, total });
      if (label) progress.message = label;
    },
    close(): void {
      progress.closed = true;
    },
  };
}
