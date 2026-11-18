// Política de seguridad de contenidos (CSP) de la interfaz compilada: qué puede cargar y ejecutar
// la página. Si algo lograra colar HTML en ella (un PDF, una respuesta de la IA), el navegador no
// ejecutaría su código ni lo enviaría a otro sitio. Ver docs/web/seguridad.md.
//
// Va en una etiqueta <meta> de index.html (vite.config.ts), en el escritorio y en el navegador: así
// vale también donde no se pueden poner cabeceras (GitHub Pages). Solo al compilar: el servidor de
// desarrollo de Vite inyecta código que la política no permite.
//
// Los workers cargados de un archivo (Python, el motor PDF, el OCR) no siguen la política de la
// página: se rigen por la de su respuesta.
import type { Plugin } from 'vite';

/** Las directivas, por versión. `desktop`: pywebview, que recibe los datos grandes de Python por 127.0.0.1. */
export function contentSecurityPolicy(desktop: boolean): string {
  const directives: Record<string, string[]> = {
    'default-src': ["'self'"],
    // Sin scripts en línea ni eval; el wasm (PDFium, onnxruntime) sí.
    'script-src': ["'self'", "'wasm-unsafe-eval'"],
    // Svelte y EmbedPDF ponen estilos en atributos `style` de sus plantillas.
    'style-src': ["'self'", "'unsafe-inline'"],
    'img-src': ["'self'", 'blob:', 'data:'],
    'font-src': ["'self'", 'data:'],
    // Los archivos abiertos (blob:) y, en el escritorio, el servidor de datos de Python (app/byte_server.py).
    'connect-src': ["'self'", 'blob:', 'data:', ...(desktop ? ['http://127.0.0.1:*'] : [])],
    'worker-src': ["'self'", 'blob:'],
    // Imprimir: el PDF en un iframe oculto (tools/viewer/document/print.ts).
    'frame-src': ['blob:'],
    'object-src': ["'none'"],
    'base-uri': ["'none'"],
    'form-action': ["'none'"],
  };
  return Object.entries(directives).map(([name, values]) => `${name} ${values.join(' ')}`).join('; ');
}

/** Añade la política y `referrer: no-referrer` a index.html al compilar. */
export function securityMeta(desktop: boolean): Plugin {
  return {
    name: 'security-meta',
    apply: 'build',
    transformIndexHtml: () => [
      { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: contentSecurityPolicy(desktop) }, injectTo: 'head-prepend' },
      { tag: 'meta', attrs: { name: 'referrer', content: 'no-referrer' }, injectTo: 'head-prepend' },
    ],
  };
}
