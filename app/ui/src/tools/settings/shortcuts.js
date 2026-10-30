// Atajos de teclado que muestra Ajustes (los mismos que la versión Qt).
// Cada atajo: [descripción, [combinación, combinación alternativa…]].

export const SHORTCUTS = [
  ['Archivo', [
    ['Abrir PDF', [['Ctrl', 'O']]],
    ['Guardar', [['Ctrl', 'S']]],
    ['Guardar como…', [['Ctrl', 'Shift', 'S']]],
    ['Imprimir', [['Ctrl', 'P']]],
    ['Cerrar pestaña', [['Ctrl', 'F4']]],
    ['Cambiar de pestaña', [['Ctrl', 'Tab'], ['Ctrl', 'Shift', 'Tab']]],
  ]],
  ['Navegación', [
    ['Página anterior', [['↑'], ['Re Pág']]],
    ['Página siguiente', [['↓'], ['Av Pág']]],
    ['Primera página', [['Inicio'], ['Ctrl', 'Inicio']]],
    ['Última página', [['Fin'], ['Ctrl', 'Fin']]],
    ['Ir a página…', [['Ctrl', 'G']]],
  ]],
  ['Zoom y vista', [
    ['Acercar', [['Ctrl', '+']]],
    ['Alejar', [['Ctrl', '−']]],
    ['Zoom 100 %', [['Ctrl', '0']]],
    ['Zoom con la rueda', [['Ctrl', 'Rueda']]],
    ['Ajustar a la página', [['Ctrl', 'H']]],
    ['Ajustar al ancho', [['Ctrl', 'W']]],
  ]],
  ['Búsqueda', [
    ['Buscar texto', [['Ctrl', 'F']]],
    ['Siguiente coincidencia', [['↓']]],
    ['Coincidencia anterior', [['↑']]],
  ]],
  ['Edición y texto', [
    ['Deshacer', [['Ctrl', 'Z']]],
    ['Rehacer', [['Ctrl', 'Y'], ['Ctrl', 'Shift', 'Z']]],
    ['Seleccionar todo el texto', [['Ctrl', 'A']]],
    ['Copiar texto seleccionado', [['Ctrl', 'C']]],
    ['Duplicar anotación', [['Ctrl', 'D']]],
    ['Eliminar selección', [['Supr']]],
    ['Cancelar selección', [['Esc']]],
  ]],
];
