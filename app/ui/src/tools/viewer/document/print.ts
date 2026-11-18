// Impresión con el diálogo de WebView2 (el de Edge): el PDF, con sus anotaciones, se abre en un
// iframe oculto y su visor de PDF lo imprime. Ese diálogo trae la vista previa, la impresora,
// las copias, las páginas (pares, impares o un rango), la orientación, el color, los márgenes,
// la escala, las páginas por hoja y la doble cara. Se imprime el PDF tal cual (vectorial: el
// texto sale nítido), sin dibujar antes cada página como imagen.
import { h } from '$lib/dom.ts';

let frame: HTMLIFrameElement | null = null; // el de la última impresión (se quita en la siguiente)

/** Abre el diálogo de impresión con `pdf` (un PDF entero). */
export async function printPdf(pdf: ArrayBuffer): Promise<void> {
  release();
  const url = URL.createObjectURL(new Blob([pdf], { type: 'application/pdf' }));
  const iframe = h('iframe', { class: 'print-frame', src: url, title: '', tabindex: '-1', 'aria-hidden': 'true' });
  frame = iframe;
  const loaded = new Promise((resolve) => iframe.addEventListener('load', resolve, { once: true }));
  document.body.append(iframe);
  await loaded;
  // El visor de PDF espera a tener el documento antes de abrir el diálogo (comprobado con 120 páginas).
  iframe.contentWindow!.focus();
  iframe.contentWindow!.print();
}

/** Quita el iframe de la impresión anterior (al imprimir otra vez o al cerrar el visor). */
export function release(): void {
  if (!frame) return;
  URL.revokeObjectURL(frame.src);
  frame.remove();
  frame = null;
}
