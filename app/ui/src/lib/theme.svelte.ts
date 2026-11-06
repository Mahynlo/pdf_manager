// Tema claro/oscuro compartido: un atributo en <html> cambia todas las variables de
// tokens.css. Cualquier componente lee `theme.dark` y se actualiza solo.
import { call } from './api.ts';

let dark = $state(false);

const REMEMBERED = 'theme'; // copia para la pantalla de carga: el tema guardado lo tiene Python

function apply(): void {
  const value = dark ? 'dark' : 'light';
  document.documentElement.dataset.theme = value;
  try {
    localStorage.setItem(REMEMBERED, value);
  } catch {
    // Sin almacenamiento, la pantalla de carga sale con el tema claro.
  }
}

export const theme = {
  get dark(): boolean {
    return dark;
  },
  /** El tema de la última vez, antes de que Python diga el guardado (pantalla de carga). */
  restore(): void {
    try {
      if (localStorage.getItem(REMEMBERED) === 'dark') document.documentElement.dataset.theme = 'dark';
    } catch {
      // Sin almacenamiento, tema claro.
    }
  },
  /** Tema guardado al arrancar (sin volver a guardarlo). */
  init(value: unknown): void {
    dark = Boolean(value);
    apply();
  },
  set(value: boolean): void {
    if (value === dark) return;
    dark = value;
    apply();
    call('app.set_theme', dark);
  },
  toggle(): void {
    theme.set(!dark);
  },
};
