// Textos de Ajustes (tools/settings).

/** Atajo: [descripción, [combinación, combinación alternativa…]]. */
type Shortcut = [string, string[][]];

export default {
  title: 'Configuración General',
  subtitle: 'Administra las preferencias y la apariencia de la aplicación',
  appearance: {
    title: 'Apariencia',
    theme: 'Tema de la aplicación',
    themeHint: 'Cambia entre tema claro y oscuro para mayor comodidad visual',
    light: 'Claro',
    dark: 'Oscuro',
  },
  shortcuts: {
    title: 'Atajos de teclado',
    or: 'o', // entre dos combinaciones del mismo atajo
    /** Los mismos que la versión Qt: [grupo, atajos]. */
    groups: [
      ['Archivo', [
        ['Abrir PDF', [['Ctrl', 'O']]],
        ['Guardar', [['Ctrl', 'S']]],
        ['Guardar como…', [['Ctrl', 'Shift', 'S']]],
        ['Imprimir', [['Ctrl', 'P']]],
        ['Cerrar pestaña', [['Ctrl', 'F4']]],
        ['Cambiar de pestaña', [['Ctrl', 'Tab'], ['Ctrl', 'Shift', 'Tab'], ['Ctrl', 'Re Pág'], ['Ctrl', 'Av Pág']]],
        ['Mover la pestaña', [['Ctrl', 'Shift', 'Re Pág'], ['Ctrl', 'Shift', 'Av Pág']]],
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
    ] as [string, Shortcut[]][],
  },
  storage: {
    title: 'Almacenamiento y Diagnóstico',
    recent: 'Historial de archivos recientes:',
    clearRecent: 'Vaciar historial',
    recentCleared: 'El historial de archivos recientes ha sido eliminado.',
    about: (v: { app: string; pdfium: string; pywebview: string; python: string }) =>
      `Extraer PDFs v${v.app} · Motor PDF: PDFium ${v.pdfium} | Entorno: ${v.pywebview === '?' ? 'navegador (Pyodide)' : `pywebview v${v.pywebview} (WebView2)`} · Python ${v.python}`,
    showLog: 'Ver Registro de Diagnóstico...',
  },
  log: {
    title: 'Registro de Diagnóstico',
    close: 'Cerrar',
  },
};
