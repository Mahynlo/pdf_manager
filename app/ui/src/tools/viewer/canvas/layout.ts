// Modos de vista del lienzo (la colocación de las páginas en cada uno la hace EmbedPDF,
// ver canvas.ts y embed.ts).

export const MODES = {
  CONTINUOUS: 'continuous',
  SINGLE: 'single',
  DOUBLE: 'double',
} as const;

export type Mode = (typeof MODES)[keyof typeof MODES];

/** Páginas que avanza «siguiente/anterior» en cada modo. */
export function pageStep(mode: Mode): number {
  return mode === MODES.DOUBLE ? 2 : 1;
}
