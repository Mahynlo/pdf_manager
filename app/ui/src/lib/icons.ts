// Iconos vectoriales (assets/icons.json). En los componentes
// se usa <Icon name="…">; `ic()` es para el código imperativo del lienzo del visor.
//
//   button.append(ic('save'));
import icons from '../assets/icons.json';

/** Trazos SVG de cada icono, por nombre. */
export const paths: Record<string, string> = icons;

export function ic(name: string, size = 16): SVGSVGElement {
  if (!(name in paths)) console.warn(`Icono desconocido: ${name}`);
  const tpl = document.createElement('template');
  tpl.innerHTML =
    `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ?? ''}</svg>`;
  return tpl.content.firstChild as SVGSVGElement;
}
