// Arranque de la interfaz: estilos, tema guardado y componente raíz.
import { mount, unmount } from 'svelte';
import App from './App.svelte';
import { call } from './lib/api.ts';
import { listenEngineTasks } from './lib/engine.ts';
import type { AppSettings } from './lib/types.ts';
import { theme } from './lib/theme.svelte.ts';
import Splash from './shell/Splash.svelte';
import { t } from '$texts';
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

// En la versión de navegador, Python tarda unos segundos en arrancar.
let splash: { fail(message: string): void } | null = null;

async function boot(): Promise<void> {
  let hint: ReturnType<typeof setTimeout> | undefined;
  if (import.meta.env.MODE === 'browser') {
    theme.restore();
    splash = mount(Splash, { target: document.body });
  } else {
    // Fuera de la app (p. ej. la URL de «pnpm dev» en un navegador) no hay backend y la
    // espera no acabaría nunca: se explica cómo abrirla en vez de dejar la página en blanco.
    hint = setTimeout(() => {
      document.body.textContent = t.shell.boot.waiting;
    }, BACKEND_HINT_MS);
  }
  const settings = await call<AppSettings>('app.settings');
  clearTimeout(hint);
  if (splash) void unmount(splash);
  splash = null;
  document.body.textContent = '';
  theme.init(settings.dark_theme);
  // En <body>: base.css lo maqueta en columna (cabecera, vistas, barra de estado).
  mount(App, { target: document.body });
  listenEngineTasks();
}

// La ventana se crea oculta y se muestra con app.ready, ya con el tema aplicado
// (sin destello blanco). Se llama también si el arranque falla, para ver el error.
boot()
  .catch((err: Error) => {
    console.error(err);
    if (splash) splash.fail(err.message);
    else document.body.textContent = t.shell.boot.failed(err.message);
  })
  .finally(() => call('app.ready'));
