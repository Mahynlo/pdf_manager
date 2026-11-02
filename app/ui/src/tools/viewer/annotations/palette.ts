// Colores y estilos de las anotaciones (como pen_color, shape_color, highlight_color y la
// barra de propiedades de Qt). Solo datos: los usan embed.ts (valores iniciales de las
// herramientas de EmbedPDF), annotations.ts, editing.ts y la barra de herramientas. Los nombres
// de los colores están en el catálogo de textos.
import { t } from '$texts';

// Estilo inicial de cada herramienta; cada visor guarda el suyo (annotations.ts).
export const DEFAULT_STYLE = {
  penColor: '#1565C0',
  shapeColor: '#00796B',
  highlightColor: '#FFD600',
  underlineColor: '#0022AA',
  strikeoutColor: '#D32F2F',
  squigglyColor: '#E53935',
  editColor: '#D32F2F', // insertar y reemplazar texto
  noteColor: '#FFD600',
  redactColor: '#000000', // relleno de la censura (lo elige el panel)
  redactOutline: '#E53935', // borde de las marcas de censura pendientes
  shapeWidth: 1.5,
  penWidth: 1.5,
  thinWidth: 0.75,
  markerWidth: 12,
  fontSize: 14,
};

export type AnnotationStyle = typeof DEFAULT_STYLE;

/** Paleta de la barra de herramientas (como los botones de color de Qt): [color, nombre]. */
export const PALETTE = t.viewer.annotations.palette;

// Barra de propiedades de la anotación seleccionada (AnnotationPropertyBar en Qt).
export const PRESET_COLORS = t.viewer.annotations.presetColors;
export const STROKE_WIDTHS = [0.75, 1.5, 3, 5, 8];
export const FONT_SIZES = [8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 40];
