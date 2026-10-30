// Tema claro/oscuro compartido: un atributo en <html> cambia todas las variables de
// tokens.css. Cualquier componente lee `theme.dark` y se actualiza solo.
import { call } from './api.js';

let dark = $state(false);

function apply() {
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

export const theme = {
  get dark() {
    return dark;
  },
  /** Tema guardado al arrancar (sin volver a guardarlo). */
  init(value) {
    dark = Boolean(value);
    apply();
  },
  set(value) {
    if (value === dark) return;
    dark = value;
    apply();
    call('app.set_theme', dark);
  },
  toggle() {
    theme.set(!dark);
  },
};
