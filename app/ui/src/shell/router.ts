// La dirección de la página sigue a la pestaña activa, como en cualquier web: /inicio, /ayuda,
// /ver/contrato.pdf… Atrás y adelante del navegador cambian de pestaña, y el título de la pestaña
// del navegador es el de la activa. Solo en la versión de navegador: en el escritorio la dirección
// no se ve (`ROUTED`).
//
// Un documento no se puede volver a abrir desde su dirección (al recargar o con un enlace): el
// navegador no deja leer un archivo que el usuario no haya vuelto a elegir. Quien usa el Router
// decide qué hacer entonces (shell.svelte.ts: aviso e Inicio).
//
// La web tiene que servir index.html en cualquier dirección (ver docs/web/navegador.md).

/** Hay direcciones: solo en la versión de navegador. */
export const ROUTED = import.meta.env.MODE === 'browser';

/** Dirección de cada herramienta (por su clave en tools.ts, más Inicio). */
const TOOL_PATHS: Record<string, string> = {
  home: 'inicio',
  extract: 'extraer',
  merge: 'unir',
  security: 'seguridad',
  settings: 'ajustes',
  help: 'ayuda',
};
const DOCUMENT_PATH = 'ver';

/** Adónde lleva una dirección: una herramienta (su clave), un documento (su nombre) o ningún sitio. */
export type Route = { tool: string } | { document: string } | null;

/** Una pestaña, para darle dirección. */
export interface Place {
  key: string;
  title: string;
  viewer: boolean; // un documento: su dirección lleva su nombre (`title`)
}

/** La dirección de `place`, desde la raíz de la web. */
export function pathOf(place: Place): string {
  if (place.viewer) return `${DOCUMENT_PATH}/${encodeURIComponent(place.title)}`;
  return TOOL_PATHS[place.key] ?? TOOL_PATHS.home;
}

/** Adónde lleva `path` (desde la raíz de la web). */
export function routeOf(path: string): Route {
  const [first, ...rest] = path.split('/').filter(Boolean);
  if (first === DOCUMENT_PATH && rest.length) {
    try {
      return { document: decodeURIComponent(rest.join('/')) };
    } catch {
      return null; // mal codificada
    }
  }
  const tool = Object.keys(TOOL_PATHS).find((key) => TOOL_PATHS[key] === first);
  return tool ? { tool } : null;
}

/** Lo que guarda cada entrada del historial: la pestaña que mostraba. */
interface HistoryState {
  key: string;
}

/**
 * Lleva la dirección y el historial del navegador. `follow` recibe adónde ir al moverse por el
 * historial: la pestaña que mostraba esa entrada (`key`, si sigue abierta se vuelve a ella) y su
 * dirección. Lo que muestre entonces sustituye a esa entrada en vez de añadir otra.
 */
export class Router {
  private readonly root = new URL(import.meta.env.BASE_URL, location.href).pathname;
  private readonly appName: string;
  private following = false;
  private started = false;

  constructor(appName: string, follow: (key: string | null, route: Route) => void) {
    this.appName = appName;
    window.addEventListener('popstate', (ev: PopStateEvent) => {
      this.following = true;
      try {
        follow((ev.state as HistoryState | null)?.key ?? null, this.current());
      } finally {
        this.following = false;
      }
    });
  }

  /** Adónde lleva la dirección actual. */
  current(): Route {
    return routeOf(location.pathname.slice(this.root.length));
  }

  /**
   * Pone la dirección y el título de `place`, la pestaña activa: una entrada nueva en el historial,
   * o sustituyendo la actual con `replace` (p. ej. cambia el nombre del documento).
   */
  show(place: Place, { replace = false } = {}): void {
    document.title = `${place.title} · ${this.appName}`;
    const path = this.root + pathOf(place);
    const state: HistoryState = { key: place.key };
    if (path === location.pathname && (history.state as HistoryState | null)?.key === place.key) return;
    if (replace || this.following || !this.started) history.replaceState(state, '', path);
    else history.pushState(state, '', path);
    this.started = true;
  }
}
