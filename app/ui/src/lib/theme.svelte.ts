// Tema claro/oscuro compartido: un atributo en <html> cambia todas las variables de
// tokens.css. Cualquier componente lee `theme.dark` y se actualiza solo.
import { call } from './api.ts';

let dark = $state(false);

function apply(): void {
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

export const theme = {
  get dark(): boolean {
    return dark;
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
