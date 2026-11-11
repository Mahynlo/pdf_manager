// Estado de la ventana principal: Inicio
// fijo, una pestaña única por herramienta y una pestaña de visor por PDF. App.svelte
// pinta la cabecera (TabStrip.svelte, en el orden de `shell.tabs`, que el usuario puede cambiar)
// y las vistas (`shell.views`, en el orden en que se abrieron: así no se mueven en la página).
//
// Cada pestaña monta su componente y guarda su instancia (bind:this) para llamar a las
// funciones que exporte: canClose(), onKey(ev) y onShow() (ver tools.ts).
//
// En la versión de navegador la dirección de la página sigue a la pestaña activa (router.ts).
import { call, on, type ApiError } from '$lib/api.ts';
import { fileName } from '$lib/dom.ts';
import type { MenuItem } from '$lib/menu.svelte.ts';
import type { DocumentInfo } from '$lib/types.ts';
import { askChoice, askPassword, setStatus, toast } from '$lib/ui.ts';
import type { Component } from 'svelte';
import { t } from '$texts';
import { ROUTED, Router, type Route } from './router.ts';
import { getTool, loadViewer, TOOLS } from './tools.ts';

export const HOME = 'home';
const MAX_TAB_LABEL = 24;
const MODIFIED_MARK = '● ';
const T = t.shell;

const docKey = (id: number) => `pdf:${id}`; // por documento del backend: no cambia con «Guardar como»

/** Funciones que puede exportar el componente de una pestaña (ver tools.ts). */
export interface TabInstance {
  canClose?(): boolean | Promise<boolean>;
  onKey?(ev: KeyboardEvent): boolean | void;
  onShow?(): void;
}

let opened = 0; // cuántas pestañas se han abierto: el orden de las vistas

class Tab {
  key: string;
  icon: string;
  closable: boolean;
  viewer: boolean;
  readonly serial = opened++;
  title = $state('');
  path = $state<string | null>(null);
  modified = $state(false);
  component = $state.raw<Component<any, TabInstance> | null>(null); // se carga al abrir la pestaña
  props = $state.raw<Record<string, unknown>>({});
  #instance: TabInstance | null = null;

  constructor(key: string, title: string, icon: string,
              { closable = true, path = null as string | null, viewer = false } = {}) {
    this.key = key;
    this.title = title;
    this.icon = icon;
    this.closable = closable;
    this.path = path;
    this.viewer = viewer;
  }

  /** Lo asigna bind:this al montar el componente (y null al desmontarlo). */
  get instance(): TabInstance | null {
    return this.#instance;
  }

  set instance(value: TabInstance | null) {
    this.#instance = value;
    if (value && this.key === shell.current) value.onShow?.();
  }

  get label(): string {
    const name = this.title.length <= MAX_TAB_LABEL ? this.title : `${this.title.slice(0, MAX_TAB_LABEL - 3)}...`;
    return `${this.modified ? MODIFIED_MARK : ''}${name}`;
  }
}

class Shell {
  tabs = $state<Tab[]>([]);
  current = $state(HOME);
  history: string[] = []; // claves en orden de uso, para volver a la anterior al cerrar
  opening = new Set<string>(); // rutas que se están abriendo (evita pestañas duplicadas)
  toggleTheme: () => void = () => {};
  router: Router | null = null;

  start(toggleTheme: () => void): void {
    this.toggleTheme = toggleTheme;
    this.router = ROUTED ? new Router(T.header.appName, (key, route) => this.follow(key, route)) : null;
    const initial = this.router?.current() ?? null;
    this.tabs.push(new Tab(HOME, T.home.title, 'home', { closable: false }));
    this.activate(HOME);
    if (initial) this.follow(null, initial);
    // Aperturas pedidas por el backend (Abrir PDF, resultados de otras herramientas…).
    on<{ path: string; password: string | null }>('document:open', ({ path, password }) => this.openDocument(path, password));
    // Se cerró la ventana con documentos sin guardar o trabajos en curso (como closeEvent en Qt).
    on<{ documents: string[]; jobs: string[] }>('app:quit-requested', ({ documents, jobs }) => this.confirmQuit(documents, jobs));
  }

  get(key: string): Tab | undefined {
    return this.tabs.find((tab) => tab.key === key);
  }

  /** Las pestañas en el orden en que se abrieron, para pintar sus vistas: reordenar las pestañas
   * no mueve las vistas en la página (perderían su desplazamiento). */
  get views(): Tab[] {
    return [...this.tabs].sort((a, b) => a.serial - b.serial);
  }

  async confirmQuit(documents: string[], jobs: string[]): Promise<void> {
    if (document.querySelector('dialog[open]')) return; // ya hay una pregunta abierta
    const list = (items: string[]) => items.map((name) => `  • ${name}`).join('\n');
    const parts = [];
    if (documents.length) parts.push(T.quit.unsaved(list(documents)));
    if (jobs.length) parts.push(T.quit.jobs(list(jobs)));
    const title = documents.length ? T.quit.unsavedTitle : T.quit.jobsTitle;
    const choice = await askChoice(title, `${parts.join('\n\n')}\n\n${T.quit.question}`, [
      { label: t.common.close, value: true, tone: 'danger' },
      { label: t.common.cancel, value: false },
    ]);
    if (choice) call('app.quit');
  }

  // ── Documentos ─────────────────────────────────────────────────────────
  async openPdfDialog(): Promise<void> {
    try {
      await call('documents.open_dialog');
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  /** Abre `path` en una pestaña de visor (o cambia a la suya si ya está abierto). */
  async openDocument(path: string, password: string | null = null): Promise<void> {
    const existing = this._documentTab(path);
    if (existing) return this.activate(existing.key);
    if (this.opening.has(path)) return;
    this.opening.add(path);
    try {
      const info = await this._loadDocument(path, password);
      if (!info) return;
      const key = docKey(info.id);
      if (this.get(key)) return this.activate(key);
      const tab = new Tab(key, info.name, 'file-text', { path: info.path, viewer: true });
      tab.props = {
        info,
        close: () => this.close(key),
        update: (next: DocumentInfo) => this._updateDocumentTab(key, next),
      };
      this.tabs.push(tab);
      this.activate(key);
      const { default: Viewer } = await loadViewer();
      if (!this.get(key)) {
        call('viewer.close_document', info.id);
        return;
      }
      tab.component = Viewer;
      setStatus(T.opened(info.name));
    } catch (err) {
      console.error(err);
      toast((err as Error).message, 'danger');
    } finally {
      this.opening.delete(path);
    }
  }

  /** `viewer.open`, pidiendo la contraseña mientras haga falta. `null` si se cancela. */
  async _loadDocument(path: string, password: string | null): Promise<DocumentInfo | null> {
    try {
      return await call<DocumentInfo>('viewer.open', path, password);
    } catch (err) {
      const code = (err as ApiError).code;
      if (code !== 'password_required' && code !== 'invalid_password') throw err;
    }
    let info: DocumentInfo | null = null;
    const unlocked = await askPassword(fileName(path), async (pwd) => {
      try {
        info = await call<DocumentInfo>('viewer.open', path, pwd);
        return null;
      } catch (err) {
        return (err as Error).message;
      }
    });
    return unlocked ? info : null;
  }

  /** Marca de cambios sin guardar y, tras «Guardar como», la nueva ruta (como _refresh_viewer_tab en Qt). */
  _updateDocumentTab(key: string, { name, path, modified }: Pick<DocumentInfo, 'name' | 'path' | 'modified'>): void {
    const tab = this.get(key);
    if (!tab) return;
    Object.assign(tab, { title: name, path, modified });
    if (key === this.current) this.router?.show(tab, { replace: true }); // su dirección lleva el nombre
  }

  _documentTab(path: string): Tab | undefined {
    const wanted = path.toLowerCase(); // Windows: las rutas no distinguen mayúsculas
    return this.tabs.find((tab) => tab.path?.toLowerCase() === wanted);
  }

  // ── Pestañas ───────────────────────────────────────────────────────────
  async open(key: string): Promise<void> {
    if (this.get(key)) return this.activate(key);
    const tool = getTool(key);
    if (!tool) return;
    const tab = new Tab(key, tool.title, tool.icon);
    tab.props = { tool };
    this.tabs.push(tab);
    this.activate(key);
    try {
      const { default: component } = await tool.load();
      tab.component = component; // si la pestaña se cerró mientras cargaba, ya no se pinta
    } catch (err) {
      console.error(err);
      toast(T.openFailed(tool.title, (err as Error).message), 'danger');
    }
  }

  activate(key: string, { replace = false } = {}): void {
    this.current = key;
    this.history = [...this.history.filter((k) => k !== key), key];
    const tab = this.get(key);
    if (tab) this.router?.show(tab, { replace });
    tab?.instance?.onShow?.();
  }

  /**
   * Va adonde lleva una entrada del historial del navegador (o la dirección al cargar la página):
   * a la pestaña `key` si sigue abierta; si no, a la herramienta de `route`. Un documento no se
   * puede volver a abrir desde su dirección: se avisa y se queda en la pestaña activa.
   */
  follow(key: string | null, route: Route): void {
    if (key && this.get(key)) this.activate(key);
    else if (route && 'tool' in route) void this.open(route.tool);
    else {
      if (route) toast(T.reopen(route.document), 'warning', 8000);
      this.activate(this.current, { replace: true });
    }
  }

  /** Cierra la pestaña; la herramienta puede impedirlo con `canClose()` (p. ej. trabajo en curso). */
  async close(key: string): Promise<void> {
    const tab = this.get(key);
    if (!tab?.closable) return;
    if (tab.instance?.canClose && !(await tab.instance.canClose())) return;
    if (!this.get(key)) return;
    this.tabs = this.tabs.filter((tab) => tab.key !== key); // desmontar el componente libera sus recursos
    this.history = this.history.filter((k) => k !== key);
    if (this.current === key) this.activate(this.history.at(-1) ?? HOME, { replace: true });
  }

  /** Cierra varias pestañas por clave, de la última a la primera (como Qt). */
  async closeMany(keys: string[]): Promise<void> {
    for (const key of [...keys].reverse()) await this.close(key);
  }

  cycle(step: number): void {
    const keys = this.tabs.map((tab) => tab.key);
    const next = (keys.indexOf(this.current) + step + keys.length) % keys.length;
    this.activate(keys[next]);
  }

  /** Si la pestaña se puede mover (Inicio va siempre la primera). */
  movable(key: string): boolean {
    return key !== HOME && Boolean(this.get(key));
  }

  /** Pone la pestaña `key` en la posición `index` (sin pasar por delante de Inicio). */
  moveTab(key: string, index: number): void {
    const from = this.tabs.findIndex((tab) => tab.key === key);
    if (from < 0 || !this.movable(key)) return;
    const to = Math.max(1, Math.min(index, this.tabs.length - 1));
    if (to === from) return;
    const tabs = [...this.tabs];
    tabs.splice(to, 0, ...tabs.splice(from, 1));
    this.tabs = tabs;
  }

  /** Mueve la pestaña `key` un sitio a la izquierda (`-1`) o a la derecha (`1`). */
  shiftTab(key: string, step: -1 | 1): void {
    this.moveTab(key, this.tabs.findIndex((tab) => tab.key === key) + step);
  }

  onKey(ev: KeyboardEvent): void {
    if (document.querySelector('dialog[open]')) return; // los diálogos modales gestionan su teclado
    const key = ev.key.toLowerCase();
    let handled = true;
    if (ev.ctrlKey && key === 'o') this.openPdfDialog();
    else if (ev.ctrlKey && key === 'f4') this.close(this.current); // Ctrl+W queda para «ajustar al ancho» del visor
    else if (ev.ctrlKey && key === 'tab') this.cycle(ev.shiftKey ? -1 : 1);
    // Como en los navegadores: Ctrl+Re Pág / Av Pág cambian de pestaña y, con Mayús, la mueven.
    else if (ev.ctrlKey && (key === 'pageup' || key === 'pagedown')) {
      const step = key === 'pageup' ? -1 : 1;
      if (ev.shiftKey) this.shiftTab(this.current, step);
      else this.cycle(step);
    }
    else handled = Boolean(this.get(this.current)?.instance?.onKey?.(ev));
    if (handled) ev.preventDefault();
  }

  // ── Menús de la cabecera ───────────────────────────────────────────────
  brandMenu(): MenuItem[] {
    const items: MenuItem[] = [{ label: T.brand.openPdf, icon: 'folder-open', onSelect: () => this.openPdfDialog() }, 'separator'];
    let section = 0;
    for (const tool of TOOLS) {
      if ((tool.section ?? 0) !== section) {
        items.push('separator');
        section = tool.section ?? 0;
      }
      items.push({ label: tool.menuLabel, icon: tool.icon, onSelect: () => this.open(tool.key) });
    }
    items.push('separator', { label: T.brand.theme, icon: 'moon', onSelect: this.toggleTheme });
    return items;
  }

  tabsMenu(): MenuItem[] {
    return this.tabs.map((tab) => ({
      label: `${tab.modified ? MODIFIED_MARK : ''}${tab.title}`, icon: tab.key === this.current ? 'check' : undefined,
      onSelect: () => this.activate(tab.key),
    }));
  }

  /** Menú contextual de una pestaña (como _show_tab_context_menu en Qt). */
  tabContextMenu(key: string): MenuItem[] {
    const keys = this.tabs.filter((tab) => tab.closable).map((tab) => tab.key);
    const index = keys.indexOf(key);
    const position = this.tabs.findIndex((tab) => tab.key === key);
    const { path } = this.get(key)!; // se lee al abrir el menú: puede cambiar con «Guardar como»
    const items: MenuItem[] = [
      { label: T.tab.close, icon: 'x', onSelect: () => this.close(key) },
      { label: T.tab.closeOthers, icon: 'x', onSelect: () => this.closeMany(keys.filter((k) => k !== key)) },
      { label: T.tab.closeRight, icon: 'arrow-right', onSelect: () => this.closeMany(keys.slice(index + 1)) },
      'separator',
      { label: T.tab.moveLeft, icon: 'chevron-left', disabled: position <= 1, onSelect: () => this.shiftTab(key, -1) },
      {
        label: T.tab.moveRight, icon: 'chevron-right', disabled: position >= this.tabs.length - 1,
        onSelect: () => this.shiftTab(key, 1),
      },
    ];
    if (path) {
      items.push('separator',
        {
          label: T.tab.copyPath, icon: 'copy',
          onSelect: () => navigator.clipboard.writeText(path).then(() => setStatus(T.tab.pathCopied)),
        },
        { label: T.tab.reveal, icon: 'folder', onSelect: () => call('documents.reveal', path) });
    }
    return items;
  }
}

export const shell = new Shell();
