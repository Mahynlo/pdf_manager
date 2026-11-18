// Barras que se compactan por niveles para caber (patrón «priority+»): en cuanto no cabe todo,
// se pasa al nivel siguiente, que agrupa o acorta algo más (lo decide el CSS con `data-level`).
//
//   <div class="viewer-toolbar" use:fit={{ levels: 3 }}>…</div>   → data-level="0" … "3"
//
// Mide el contenido de verdad (no depende de cortes fijos): vale con ratón o dedo, con el panel
// lateral abierto o cerrado. Si ni el último nivel cabe, la barra se desplaza (lib/strip.ts).
import type { Action } from 'svelte/action';

export interface FitOptions {
  /** El nivel más compacto. */
  levels: number;
}

export const fit: Action<HTMLElement, FitOptions> = (node, initial) => {
  let { levels } = initial;

  const overflows = () => node.scrollWidth > node.clientWidth + 1;
  const measure = () => {
    if (!node.clientWidth) return; // oculta: se mide al mostrarla
    let level = 0;
    node.dataset.level = '0';
    while (level < levels && overflows()) node.dataset.level = String(++level); // cada lectura recalcula
  };

  // Su ancho lo pone quien la contiene: cambiar de nivel no vuelve a disparar el observador.
  const resize = new ResizeObserver(measure);
  resize.observe(node);
  measure();

  return {
    update(next) {
      levels = next.levels;
      measure();
    },
    destroy() {
      resize.disconnect();
    },
  };
};
