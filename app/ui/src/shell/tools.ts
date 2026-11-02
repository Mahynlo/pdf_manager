// Registro de herramientas: el único sitio que hay que tocar para añadir una
// (equivale a src_qt/ui/shell/tool_registry.py). De aquí salen las pestañas, el menú
// de la marca y las tarjetas de Inicio.
//
// `load` importa el componente de la herramienta (se carga al abrirla). Recibe la
// entrada del registro como prop `tool` y puede exportar las funciones de pestaña
// que usa el shell: canClose() (puede impedir el cierre), onKey(ev) (atajos cuando es
// la pestaña activa; devuelve true si los gestionó) y onShow(). Los nombres y las tarjetas
// están en el catálogo de textos (t.shell.tools).
import type { Component } from 'svelte';
import { t } from '$texts';

const T = t.shell.tools;

/** Tarjeta de Inicio: título y texto (con saltos de línea). */
export interface Card {
  title: string;
  text: string;
}

type Loader = () => Promise<{ default: Component<any> }>;

export interface Tool {
  key: string;
  title: string; // pestaña
  menuLabel: string; // menú de la marca
  icon: string;
  emoji: string;
  color: string;
  card?: Card; // sin tarjeta no sale en Inicio
  section?: number; // grupo en el menú de la marca (separador entre grupos)
  load: Loader;
}

/** Tarjeta de Inicio que ejecuta una acción en vez de abrir una herramienta. */
export interface HomeAction {
  after: string; // clave de la herramienta tras la que va
  action: 'open-pdf';
  emoji: string;
  color: string;
  card: Card;
}

/** Tarjeta de Inicio: una herramienta (`tool`, su clave) o una acción. */
export interface HomeCard {
  emoji: string;
  color: string;
  card: Card;
  tool?: string;
  action?: HomeAction['action'];
}

export const TOOLS: Tool[] = [
  {
    key: 'extract', ...T.extract, icon: 'search', emoji: '🔍', color: '#1A73E8',
    load: () => import('../tools/extract/Extract.svelte'),
  },
  {
    key: 'merge', ...T.merge, icon: 'files', emoji: '📑', color: '#2E7D32',
    load: () => import('../tools/merge/Merge.svelte'),
  },
  {
    key: 'security', ...T.security, icon: 'lock', emoji: '🔒', color: '#F9A825',
    load: () => import('../tools/security/Security.svelte'),
  },
  {
    key: 'settings', ...T.settings, icon: 'settings', emoji: '⚙️', color: '#607D8B', section: 1,
    load: () => import('../tools/settings/Settings.svelte'),
  },
  {
    key: 'help', ...T.help, icon: 'circle-help', emoji: '❓', color: '#7E57C2', section: 1,
    load: () => import('../tools/help/Help.svelte'),
  },
];

/** Visor de PDF: una pestaña por documento (no está en el menú ni en Inicio). */
export const loadViewer: Loader = () => import('../tools/viewer/Viewer.svelte');

// Tarjetas de Inicio que ejecutan una acción en vez de abrir una herramienta
// (se colocan tras la herramienta indicada en `after`).
export const HOME_ACTIONS: HomeAction[] = [
  {
    after: 'merge', action: 'open-pdf', emoji: '📄', color: '#E65100', card: t.shell.actions.openPdf,
  },
];

export function getTool(key: string): Tool | undefined {
  return TOOLS.find((tool) => tool.key === key);
}

/** Tarjetas de Inicio en orden. */
export function homeCards(): HomeCard[] {
  const cards: HomeCard[] = [];
  for (const tool of TOOLS) {
    if (tool.card) cards.push({ ...tool, card: tool.card, tool: tool.key });
    cards.push(...HOME_ACTIONS.filter((a) => a.after === tool.key));
  }
  return cards;
}
