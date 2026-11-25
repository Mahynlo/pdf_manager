// Conversiones de color para el selector (ColorPanel.svelte): «#RRGGBB» ↔ HSV (matiz 0–360,
// saturación y brillo 0–1), que es como se elige en el cuadro y la barra de matiz.

export interface Hsv {
  h: number;
  s: number;
  v: number;
}

const HEX = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i;

/** «#abc», «abc», «#AABBCC» → «#AABBCC»; null si no es un color. */
export function normalizeHex(text: string): string | null {
  const match = HEX.exec(text.trim());
  if (!match) return null;
  const digits = match[1].length === 3 ? [...match[1]].map((d) => d + d).join('') : match[1];
  return `#${digits.toUpperCase()}`;
}

export function hexToHsv(hex: string): Hsv {
  const value = normalizeHex(hex) ?? '#000000';
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  let h = 0;
  if (delta) {
    if (max === r) h = ((g - b) / delta) % 6;
    else if (max === g) h = (b - r) / delta + 2;
    else h = (r - g) / delta + 4;
  }
  return { h: (h * 60 + 360) % 360, s: max ? delta / max : 0, v: max };
}

export function hsvToHex({ h, s, v }: Hsv): string {
  const f = (n: number) => {
    const k = (n + h / 60) % 6;
    return v - v * s * Math.max(0, Math.min(k, 4 - k, 1));
  };
  return `#${[f(5), f(3), f(1)].map((c) => Math.round(c * 255).toString(16).padStart(2, '0')).join('').toUpperCase()}`;
}

/** ¿Se lee mejor el texto oscuro que el blanco sobre `hex`? (para la marca de seleccionado). */
export function isLight(hex: string): boolean {
  const value = normalizeHex(hex);
  if (!value) return true;
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));
  return r * 0.299 + g * 0.587 + b * 0.114 > 160;
}
