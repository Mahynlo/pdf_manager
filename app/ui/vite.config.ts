// Interfaz de la app en Svelte. Compila a app/ui/dist/, que abre pywebview
// (``python -m app.main``, que la recompila si cambió). ``python -m app.main --dev``
// arranca además el servidor de Vite (``pnpm dev``) y abre la ventana con recarga al
// guardar. Ver docs/web/svelte.md.
//
// Con `--mode browser` compila la versión de navegador a app/ui/dist-web/ (`pnpm build:web`,
// `pnpm dev:web`). Ver docs/web/navegador.md.
//
// Svelte usa su configuración predeterminada: no hace falta svelte.config.js.
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

// Sin aislar la página no hay memoria compartida, y Python la necesita (lib/browser/protocol.ts).
const ISOLATED = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
};

export default defineConfig(({ mode }) => {
  const browser = mode === 'browser';
  return {
  plugins: [svelte()],
  // Rutas desde la raíz de app/ui (Vite las resuelve allí); las mismas que en tsconfig.json.
  resolve: { alias: { $lib: '/src/lib', $texts: '/src/texts' } },
  base: './', // rutas relativas: pywebview sirve dist/ como raíz
  build: { outDir: browser ? 'dist-web' : 'dist', emptyOutDir: true },
  publicDir: browser ? 'public-web' : 'public',
  worker: { format: 'es' as const },
  server: {
    port: browser ? 5174 : 5173,
    strictPort: true,
    headers: browser ? ISOLATED : {},
  },
  preview: { port: 5174, strictPort: true, headers: ISOLATED },
  };
});
