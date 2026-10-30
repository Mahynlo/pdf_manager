// Iconos vectoriales (assets/icons.json, el mismo juego que la versión Qt). En los componentes
// se usa <Icon name="…">; `ic()` es para el código imperativo del lienzo del visor.
//
//   button.append(ic('save'));
import paths from '../assets/icons.json';

export { paths };

export function ic(name, size = 16) {
  if (!(name in paths)) console.warn(`Icono desconocido: ${name}`);
  const tpl = document.createElement('template');
  tpl.innerHTML =
    `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ?? ''}</svg>`;
  return tpl.content.firstChild;
}
