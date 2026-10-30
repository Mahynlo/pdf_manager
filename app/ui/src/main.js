// Arranque de la interfaz: estilos, tema guardado y componente raíz.
import { mount } from 'svelte';
import App from './App.svelte';
import { call } from './lib/api.js';
import { theme } from './lib/theme.svelte.js';
// Estilos globales (tokens.css: colores del tema; el resto, por área de la app).
import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import './styles/shell.css';
import './styles/merge.css';
import './styles/security.css';
import './styles/extract.css';
import './styles/settings.css';
import './styles/help.css';
import './styles/viewer.css';

const BACKEND_HINT_MS = 4000;

async function boot() {
  // Fuera de la app (p. ej. la URL de «pnpm dev» en un navegador) no hay backend y la
  // espera no acabaría nunca: se explica cómo abrirla en vez de dejar la página en blanco.
  const hint = setTimeout(() => {
    document.body.textContent = 'Esperando al backend de Python… Esta interfaz se abre desde la app: '
      + 'ejecuta «uv run python -m app.main --dev» desde la raíz del proyecto.';
  }, BACKEND_HINT_MS);
  const settings = await call('app.settings');
  clearTimeout(hint);
  document.body.textContent = '';
  theme.init(settings.dark_theme);
  // En <body>: base.css lo maqueta en columna (cabecera, vistas, barra de estado).
  mount(App, { target: document.body });
}

// La ventana se crea oculta y se muestra con app.ready, ya con el tema aplicado
// (sin destello blanco). Se llama también si el arranque falla, para ver el error.
boot()
  .catch((err) => {
    console.error(err);
    document.body.textContent = `Error al iniciar la interfaz: ${err.message}`;
  })
  .finally(() => call('app.ready'));
