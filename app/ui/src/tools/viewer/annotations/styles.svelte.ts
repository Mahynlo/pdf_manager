// Estilo de las anotaciones: los colores de la paleta y lo que recuerda cada herramienta (color,
// grosor, relleno, tamaño de letra). Lo comparten todos los visores y se guarda en el navegador
// (solo una comodidad: sin almacenamiento se empieza cada vez con los valores de aquí).
//
// Lo usan embed.ts (valores iniciales de EmbedPDF), annotations.ts (estilo al activar una
// herramienta y al marcar texto), la barra de anotaciones (ToolsBar.svelte) y la barra de la
// selección (editing.ts). Los nombres de los colores están en el catálogo de textos.
//
// Las herramientas van por su nombre (el de TOOLS en canvas.ts): importar TOOLS desde aquí haría
// un ciclo (canvas → embed → este módulo).
import { t } from '$texts';

export interface ToolStyle {
  color: string;
  width?: number; // grosor del trazo, en puntos
  fill?: string; // relleno; NO_FILL: sin relleno
  fontSize?: number; // en puntos
}

/** Sin relleno (así lo entiende EmbedPDF). */
export const NO_FILL = 'transparent';

/** Paleta: [color, nombre], dos filas de 7 (vivos; oscuros y neutros). */
export const PRESETS: [string, string][] = t.viewer.annotations.presetColors;
/** Los de la barra de anotaciones, a un clic. */
export const QUICK_COLORS = ['#FFD600', '#4CAF50', '#2196F3', '#9C27B0', '#F44336', '#000000'];

/** Grosor y tamaño de letra: límites y valores rápidos. */
export const WIDTH = { min: 0.5, max: 100, step: 0.5, presets: [1, 2, 4, 8, 16, 32] };
export const FONT_SIZE = { min: 6, max: 96, step: 1, presets: [8, 10, 12, 14, 18, 24, 36, 48] };

// Lo que recuerda cada herramienta (las propiedades que tiene son las que se pueden cambiar).
const DEFAULTS: Record<string, ToolStyle> = {
  highlight: { color: '#FFD600' },
  underline: { color: '#1565C0' },
  strikeout: { color: '#D32F2F' },
  squiggly: { color: '#E53935' },
  edit: { color: '#D32F2F' }, // insertar y reemplazar texto
  rect: { color: '#00796B', width: 1.5, fill: NO_FILL },
  ellipse: { color: '#00796B', width: 1.5, fill: NO_FILL },
  polygon: { color: '#00796B', width: 1.5, fill: NO_FILL },
  polyline: { color: '#00796B', width: 1.5 },
  line: { color: '#1565C0', width: 1.5 },
  arrow: { color: '#1565C0', width: 1.5 },
  pen: { color: '#1565C0', width: 1.5 },
  marker: { color: '#FFD600', width: 12 },
  draw: { color: '#1565C0', width: 1 },
  text: { color: '#1565C0', fontSize: 14 },
  callout: { color: '#1565C0', fontSize: 14 },
  note: { color: '#FFD600' },
};
// Herramientas que comparten estilo.
const SHARED: Record<string, string> = { 'insert-text': 'edit', 'replace-text': 'edit' };

const STORE = 'annotation-styles';
const RECENT_MAX = 7;

function load(): { tools: Record<string, ToolStyle>; recent: string[] } {
  const tools = structuredClone(DEFAULTS);
  let recent: string[] = [];
  try {
    const saved = JSON.parse(localStorage.getItem(STORE) ?? '{}');
    for (const [key, style] of Object.entries(saved.tools ?? {})) {
      if (tools[key]) tools[key] = { ...tools[key], ...sanitize(tools[key], style as ToolStyle) };
    }
    recent = (saved.recent ?? []).filter(isColor).slice(0, RECENT_MAX);
  } catch {
    // sin almacenamiento o con datos de otra versión: los valores de aquí
  }
  return { tools, recent };
}

const isColor = (value: unknown): value is string => typeof value === 'string' && /^#[0-9A-F]{6}$/i.test(value);
const clamp = (value: number, { min, max }: { min: number; max: number }) => Math.min(max, Math.max(min, value));

/** Solo las propiedades que tiene la herramienta, con valores válidos. */
function sanitize(base: ToolStyle, style: Partial<ToolStyle>): Partial<ToolStyle> {
  const out: Partial<ToolStyle> = {};
  if (isColor(style.color)) out.color = style.color.toUpperCase();
  if (base.width != null && Number.isFinite(style.width)) out.width = clamp(style.width!, WIDTH);
  if (base.fill != null && (style.fill === NO_FILL || isColor(style.fill))) out.fill = style.fill;
  if (base.fontSize != null && Number.isFinite(style.fontSize)) out.fontSize = clamp(style.fontSize!, FONT_SIZE);
  return out;
}

export const styles = $state(load());

function save(): void {
  try {
    localStorage.setItem(STORE, JSON.stringify(styles));
  } catch {
    // no se recuerda entre sesiones; en esta sí
  }
}

const keyOf = (tool: string) => SHARED[tool] ?? tool;

/** Estilo de `tool` (null si no tiene: mano, selección, imagen…). */
export function styleOf(tool: string): ToolStyle | null {
  return styles.tools[keyOf(tool)] ?? null;
}

/** Cambia el estilo de `tool` (solo lo que tiene). */
export function setStyle(tool: string, patch: Partial<ToolStyle>): void {
  const style = styles.tools[keyOf(tool)];
  if (!style) return;
  Object.assign(style, sanitize(style, patch));
  save();
}

/** Un color elegido a mano: el primero de los recientes. */
export function rememberColor(color: string): void {
  if (!isColor(color) || PRESETS.some(([preset]) => preset === color.toUpperCase())) return;
  styles.recent = [color.toUpperCase(), ...styles.recent.filter((c) => c !== color.toUpperCase())].slice(0, RECENT_MAX);
  save();
}

/** Valores iniciales (para EmbedPDF al arrancar). */
export const INITIAL = DEFAULTS;
