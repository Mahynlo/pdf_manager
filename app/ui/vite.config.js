// Interfaz de la app en Svelte. Compila a app/ui/dist/, que abre pywebview
// (``python -m app.main``, que la recompila si cambió). ``python -m app.main --dev``
// arranca además el servidor de Vite (``pnpm dev``) y abre la ventana con recarga al
// guardar. Ver docs/web/svelte.md.
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const here = (path) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig({
  plugins: [svelte()],
  resolve: { alias: { $lib: here('src/lib') } },
  base: './', // rutas relativas: pywebview sirve dist/ como raíz
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    strictPort: true,
  },
});
