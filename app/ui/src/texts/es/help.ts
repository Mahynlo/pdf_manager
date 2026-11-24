// Textos de Ayuda (tools/help). Las guías no están aquí: son Markdown en src/assets/ayuda/
// (el servicio `help` las da en HTML, con su título, icono, resumen e índice).

export default {
  title: 'Ayuda y Guía de Uso',
  subtitle: 'Cómo usar cada herramienta de Extraer PDFs',
  search: 'Buscar en la ayuda…',
  searchLabel: 'Buscar en la ayuda',
  clearSearch: 'Borrar la búsqueda',
  noResults: (query: string) => `No hay nada sobre «${query}». Prueba con otra palabra.`,
  results: (n: number) => (n === 1 ? '1 resultado' : `${n} resultados`),
  guides: 'Guías',
  onThisPage: 'En esta guía',
  showGuides: 'Ver las guías',
  previous: 'Anterior',
  next: 'Siguiente',
  empty: 'No hay guías de ayuda.',
  loading: 'Cargando…',
  zoomImage: 'Ver la imagen en grande',
  closeImage: 'Cerrar la imagen',
  /** Guía de los atajos: no es Markdown, sale de la lista de Configuración (t.settings.shortcuts). */
  shortcuts: {
    title: 'Atajos de teclado',
    icon: 'keyboard',
    summary: 'Las combinaciones de teclas del visor y de la ventana. También están en Configuración.',
    or: 'o',
  },
};
