// Modos de vista del lienzo (la colocación de las páginas en cada uno la hace EmbedPDF,
// ver canvas.js y embed.js).

export const MODES = {
  CONTINUOUS: 'continuous',
  SINGLE: 'single',
  DOUBLE: 'double',
};

/** Páginas que avanza «siguiente/anterior» en cada modo. */
export function pageStep(mode) {
  return mode === MODES.DOUBLE ? 2 : 1;
}
