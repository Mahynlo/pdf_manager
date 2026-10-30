// Registro de herramientas: el único sitio que hay que tocar para añadir una
// (equivale a src_qt/ui/shell/tool_registry.py). De aquí salen las pestañas, el menú
// de la marca y las tarjetas de Inicio.
//
// `load` importa el componente de la herramienta (se carga al abrirla). Recibe la
// entrada del registro como prop `tool` y puede exportar las funciones de pestaña
// que usa el shell: canClose() (puede impedir el cierre), onKey(ev) (atajos cuando es
// la pestaña activa; devuelve true si los gestionó) y onShow().

export const TOOLS = [
  {
    key: 'extract', title: 'Extraer', menuLabel: 'Extraer texto', icon: 'search', emoji: '🔍', color: '#1A73E8',
    card: { title: 'Extraer texto de PDF', text: 'Busca y extrae páginas\npor palabras clave' },
    load: () => import('../tools/extract/Extract.svelte'),
  },
  {
    key: 'merge', title: 'Combinar', menuLabel: 'Combinar PDFs', icon: 'files', emoji: '📑', color: '#2E7D32',
    card: { title: 'Combinar PDFs', text: 'Une varios PDFs\neligiendo las páginas' },
    load: () => import('../tools/merge/Merge.svelte'),
  },
  {
    key: 'security', title: 'Seguridad', menuLabel: 'Seguridad', icon: 'lock', emoji: '🔒', color: '#F9A825',
    card: { title: 'Gestión de Seguridad', text: 'Desbloquea y protege\ntus documentos' },
    load: () => import('../tools/security/Security.svelte'),
  },
  {
    key: 'settings', title: 'Ajustes', menuLabel: 'Configuración', icon: 'settings', emoji: '⚙️', color: '#607D8B', section: 1,
    load: () => import('../tools/settings/Settings.svelte'),
  },
  {
    key: 'help', title: 'Ayuda', menuLabel: 'Ayuda', icon: 'circle-help', emoji: '❓', color: '#7E57C2', section: 1,
    load: () => import('../tools/help/Help.svelte'),
  },
];

/** Visor de PDF: una pestaña por documento (no está en el menú ni en Inicio). */
export const loadViewer = () => import('../tools/viewer/Viewer.svelte');

// Tarjetas de Inicio que ejecutan una acción en vez de abrir una herramienta
// (se colocan tras la herramienta indicada en `after`).
export const HOME_ACTIONS = [
  {
    after: 'merge', action: 'open-pdf', emoji: '📄', color: '#E65100',
    card: { title: 'OCR de PDF', text: 'Abre un PDF y ejecuta\nreconocimiento de texto' },
  },
];

export function getTool(key) {
  return TOOLS.find((t) => t.key === key);
}

/** Tarjetas de Inicio en orden: [{ emoji, color, card, tool? , action? }]. */
export function homeCards() {
  const cards = [];
  for (const tool of TOOLS) {
    if (tool.card) cards.push({ ...tool, tool: tool.key });
    cards.push(...HOME_ACTIONS.filter((a) => a.after === tool.key));
  }
  return cards;
}
