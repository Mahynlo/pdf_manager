// Tamaño de la ventana para lo que no se puede resolver solo con CSS (abrir un panel, el zoom
// inicial). Los cortes son las clases de ventana de Material 3 y coinciden con styles/responsive.css.

function media(query: string): { readonly matches: boolean } {
  const list = matchMedia(query);
  let matches = $state(list.matches);
  list.addEventListener('change', (ev) => (matches = ev.matches));
  return {
    get matches() {
      return matches;
    },
  };
}

const compact = media('(max-width: 599.98px)');
const narrow = media('(max-width: 839.98px)');
const short = media('(max-height: 500px)');
const touch = media('(pointer: coarse)');

export const viewport = {
  /** Móvil en vertical: los paneles ocupan toda la pantalla. */
  get compact(): boolean {
    return compact.matches;
  },
  /** Hasta tableta en vertical: no caben a la vez la página y las columnas laterales. */
  get narrow(): boolean {
    return narrow.matches;
  },
  /** Falta sitio para leer (móvil en vertical u horizontal): las barras opcionales empiezan ocultas. */
  get reading(): boolean {
    return compact.matches || short.matches;
  },
  /** El puntero principal es un dedo: arrastrar desplaza, no selecciona. */
  get touch(): boolean {
    return touch.matches;
  },
};
