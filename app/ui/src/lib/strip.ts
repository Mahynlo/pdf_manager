// Tiras horizontales que pueden no caber (las pestañas, las barras del visor): se desplazan con la
// rueda del ratón y dicen por qué lado hay más, para que se vea que siguen.
//
//   <div class="tabbar" use:strip={{ onOverflow: (o) => (overflow = o) }}>…</div>
//
// Marca el elemento con `data-more-start` / `data-more-end` mientras haya contenido oculto a ese
// lado (styles/base.css difumina ese borde). Con el dedo, la tira se desliza sola (overflow-x).
import type { Action } from 'svelte/action';

/** Si hay contenido oculto a cada lado. */
export interface Overflow {
  start: boolean;
  end: boolean;
}

export interface StripOptions {
  /** Cambió lo que queda oculto (también al cambiar de tamaño la tira o su contenido). */
  onOverflow?: (overflow: Overflow) => void;
}

const LINE_PX = 16; // la rueda en líneas (Firefox) a píxeles
const SLACK_PX = 1; // redondeos de los píxeles fraccionarios

export const strip: Action<HTMLElement, StripOptions | undefined> = (node, initial) => {
  let options = initial ?? {};
  let last = '';

  const update = () => {
    const max = node.scrollWidth - node.clientWidth;
    const overflow = { start: node.scrollLeft > SLACK_PX, end: node.scrollLeft < max - SLACK_PX };
    node.toggleAttribute('data-more-start', overflow.start);
    node.toggleAttribute('data-more-end', overflow.end);
    const signature = `${overflow.start}${overflow.end}`;
    if (signature === last) return;
    last = signature;
    options.onOverflow?.(overflow);
  };

  // La rueda vertical desplaza en horizontal, como en las pestañas de los navegadores. Con Ctrl
  // sigue siendo el zoom; si la tira cabe, la rueda hace lo de siempre.
  const onWheel = (ev: WheelEvent) => {
    if (ev.ctrlKey || node.scrollWidth <= node.clientWidth) return;
    if (Math.abs(ev.deltaY) <= Math.abs(ev.deltaX)) return; // ya es horizontal (trackpad)
    ev.preventDefault();
    node.scrollLeft += ev.deltaMode === WheelEvent.DOM_DELTA_LINE ? ev.deltaY * LINE_PX : ev.deltaY;
  };

  const resize = new ResizeObserver(update);
  const children = new MutationObserver(() => {
    for (const child of node.children) resize.observe(child);
    update();
  });
  resize.observe(node);
  for (const child of node.children) resize.observe(child);
  children.observe(node, { childList: true });
  node.addEventListener('scroll', update, { passive: true });
  node.addEventListener('wheel', onWheel, { passive: false });
  update();

  return {
    update(next) {
      options = next ?? {};
      last = '';
      update();
    },
    destroy() {
      resize.disconnect();
      children.disconnect();
      node.removeEventListener('scroll', update);
      node.removeEventListener('wheel', onWheel);
    },
  };
};

/** Desplaza la tira casi una pantalla hacia un lado (`-1`: al principio; `1`: al final). */
export function scrollStrip(node: HTMLElement, direction: -1 | 1): void {
  const behavior = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  node.scrollBy({ left: direction * node.clientWidth * 0.75, behavior });
}
