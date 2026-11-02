// Colores y estilos de las anotaciones (como pen_color, shape_color, highlight_color y la
// barra de propiedades de Qt). Solo datos: los usan embed.js (valores iniciales de las
// herramientas de EmbedPDF), annotations.js, editing.js y la barra de herramientas.

// Estilo inicial de cada herramienta; cada visor guarda el suyo (annotations.js).
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

/** Paleta de la barra de herramientas (como los botones de color de Qt). */
export const PALETTE = [
  ['#FBC02D', 'Amarillo'], ['#43A047', 'Verde'], ['#1E88E5', 'Azul'],
  ['#8E24AA', 'Púrpura'], ['#E53935', 'Rojo'], ['#000000', 'Negro'],
];

// Barra de propiedades de la anotación seleccionada (AnnotationPropertyBar en Qt).
export const PRESET_COLORS = [
  ['#FFD600', 'Amarillo'], ['#4CAF50', 'Verde'], ['#2196F3', 'Azul'], ['#F44336', 'Rojo'],
  ['#9C27B0', 'Morado'], ['#FF9800', 'Naranja'], ['#212121', 'Negro'],
];
export const STROKE_WIDTHS = [0.75, 1.5, 3, 5, 8];
export const FONT_SIZES = [8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 40];
