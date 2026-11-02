// Impresión: las páginas (con sus anotaciones) se colocan en una capa solo para
// impresión (#print-root, ver viewer.css) y se abre el diálogo de impresión del
// sistema, donde se eligen la impresora, las copias y la doble cara. Así funciona
// igual en la ventana de escritorio y en un navegador. Las opciones las elige
// PrintDialog.svelte.
import { h } from '$lib/dom.js';

/**
 * `pages`: índices a imprimir; `images`: url de cada una (blob:, se liberan al terminar);
 * `sizes`: tamaño de las páginas en puntos; `scale`: fit | real | fill;
 * `orientation(página)`: portrait | landscape.
 */
export function printSheets(pages, images, sizes, { scale, orientation }) {
  document.getElementById('print-root')?.remove();
  const root = h('div', { id: 'print-root', 'data-scale': scale },
    pages.map((page, i) => {
      const [w] = sizes[page];
      return h('div', { class: `print-sheet print-sheet--${orientation(page)}` },
        h('img', { alt: '', src: images[i], style: scale === 'real' ? { width: `${w}pt` } : {} }));
    }));
  document.body.append(root);
  window.addEventListener('afterprint', () => {
    root.remove();
    for (const url of new Set(images)) URL.revokeObjectURL(url);
  }, { once: true });
  // Espera a que las imágenes estén decodificadas: si no, alguna hoja saldría en blanco.
  Promise.all([...root.querySelectorAll('img')].map((img) => img.decode().catch(() => {})))
    .then(() => window.print());
}
