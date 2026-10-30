// Estado de la ventana principal (equivale a src_qt/ui/shell/main_window.py): Inicio
// fijo, una pestaña única por herramienta y una pestaña de visor por PDF. App.svelte
// pinta la cabecera y las vistas a partir de `shell.tabs`.
//
// Cada pestaña monta su componente y guarda su instancia (bind:this) para llamar a las
// funciones que exporte: canClose(), onKey(ev) y onShow() (ver tools.js).
import { call, on } from '$lib/api.js';
import { fileName } from '$lib/dom.js';
import { askChoice, askPassword, setStatus, toast } from '$lib/ui.js';
import { getTool, loadViewer, TOOLS } from './tools.js';

export const HOME = 'home';
const MAX_TAB_LABEL = 24;
const MODIFIED_MARK = '● ';

const docKey = (id) => `pdf:${id}`; // por documento del backend: no cambia con «Guardar como»

class Tab {
  title = $state('');
  path = $state(null);
  modified = $state(false);
  component = $state.raw(null); // se carga al abrir la pestaña
  props = $state.raw({});
  #instance = null;

  constructor(key, title, icon, { closable = true, path = null, viewer = false } = {}) {
    Object.assign(this, { key, title, icon, closable, path, viewer });
  }

  /** Lo asigna bind:this al montar el componente (y null al desmontarlo). */
  get instance() {
    return this.#instance;
  }

  set instance(value) {
    this.#instance = value;
    if (value && this.key === shell.current) value.onShow?.();
  }

  get label() {
    const name = this.title.length <= MAX_TAB_LABEL ? this.title : `${this.title.slice(0, MAX_TAB_LABEL - 3)}...`;
    return `${this.modified ? MODIFIED_MARK : ''}${name}`;
  }
}

class Shell {
  tabs = $state([]);
  current = $state(HOME);
  history = []; // claves en orden de uso, para volver a la anterior al cerrar
  opening = new Set(); // rutas que se están abriendo (evita pestañas duplicadas)

  start(toggleTheme) {
    this.toggleTheme = toggleTheme;
    this.tabs.push(new Tab(HOME, 'Inicio', 'home', { closable: false }));
    this.activate(HOME);
    // Aperturas pedidas por el backend (Abrir PDF, resultados de otras herramientas…).
    on('document:open', ({ path, password }) => this.openDocument(path, password));
    // Se cerró la ventana con documentos sin guardar o trabajos en curso (como closeEvent en Qt).
    on('app:quit-requested', ({ documents, jobs }) => this.confirmQuit(documents, jobs));
  }

  get(key) {
    return this.tabs.find((t) => t.key === key);
  }

  async confirmQuit(documents, jobs) {
    if (document.querySelector('dialog[open]')) return; // ya hay una pregunta abierta
    const list = (items) => items.map((name) => `  • ${name}`).join('\n');
    const parts = [];
    if (documents.length) parts.push(`Los siguientes documentos tienen cambios sin guardar:\n\n${list(documents)}`);
    if (jobs.length) parts.push(`Se cancelarán los trabajos en curso:\n\n${list(jobs)}`);
    const title = documents.length ? 'Archivos sin guardar' : 'Trabajo en curso';
    const choice = await askChoice(title, `${parts.join('\n\n')}\n\n¿Cerrar la aplicación de todos modos?`, [
      { label: 'Cerrar', value: true, tone: 'danger' },
      { label: 'Cancelar', value: false },
    ]);
    if (choice) call('app.quit');
  }

  // ── Documentos ─────────────────────────────────────────────────────────
  async openPdfDialog() {
    try {
      await call('documents.open_dialog');
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  /** Abre `path` en una pestaña de visor (o cambia a la suya si ya está abierto). */
  async openDocument(path, password = null) {
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
        update: (next) => this._updateDocumentTab(key, next),
      };
      this.tabs.push(tab);
      this.activate(key);
      const { default: Viewer } = await loadViewer();
      if (!this.get(key)) return call('viewer.close_document', info.id);
      tab.component = Viewer;
      setStatus(`Abierto: ${info.name}`);
    } catch (err) {
      console.error(err);
      toast(err.message, 'danger');
    } finally {
      this.opening.delete(path);
    }
  }

  /** `viewer.open`, pidiendo la contraseña mientras haga falta. `null` si se cancela. */
  async _loadDocument(path, password) {
    try {
      return await call('viewer.open', path, password);
    } catch (err) {
      if (err.code !== 'password_required' && err.code !== 'invalid_password') throw err;
    }
    let info = null;
    const unlocked = await askPassword(fileName(path), async (pwd) => {
      try {
        info = await call('viewer.open', path, pwd);
        return null;
      } catch (err) {
        return err.message;
      }
    });
    return unlocked ? info : null;
  }

  /** Marca de cambios sin guardar y, tras «Guardar como», la nueva ruta (como _refresh_viewer_tab en Qt). */
  _updateDocumentTab(key, { name, path, modified }) {
    const tab = this.get(key);
    if (tab) Object.assign(tab, { title: name, path, modified });
  }

  _documentTab(path) {
    const wanted = path.toLowerCase(); // Windows: las rutas no distinguen mayúsculas
    return this.tabs.find((t) => t.path?.toLowerCase() === wanted);
  }

  // ── Pestañas ───────────────────────────────────────────────────────────
  async open(key) {
    if (this.get(key)) return this.activate(key);
    const tool = getTool(key);
    const tab = new Tab(key, tool.title, tool.icon);
    tab.props = { tool };
    this.tabs.push(tab);
    this.activate(key);
    try {
      const { default: component } = await tool.load();
      tab.component = component; // si la pestaña se cerró mientras cargaba, ya no se pinta
    } catch (err) {
      console.error(err);
      toast(`No se pudo abrir ${tool.title}: ${err.message}`, 'danger');
    }
  }

  activate(key) {
    this.current = key;
    this.history = [...this.history.filter((k) => k !== key), key];
    this.get(key)?.instance?.onShow?.();
  }

  /** Cierra la pestaña; la herramienta puede impedirlo con `canClose()` (p. ej. trabajo en curso). */
  async close(key) {
    const tab = this.get(key);
    if (!tab?.closable) return;
    if (tab.instance?.canClose && !(await tab.instance.canClose())) return;
    if (!this.get(key)) return;
    this.tabs = this.tabs.filter((t) => t.key !== key); // desmontar el componente libera sus recursos
    this.history = this.history.filter((k) => k !== key);
    if (this.current === key) this.activate(this.history.at(-1) ?? HOME);
  }

  /** Cierra varias pestañas por clave, de la última a la primera (como Qt). */
  async closeMany(keys) {
    for (const key of [...keys].reverse()) await this.close(key);
  }

  cycle(step) {
    const keys = this.tabs.map((t) => t.key);
    const next = (keys.indexOf(this.current) + step + keys.length) % keys.length;
    this.activate(keys[next]);
  }

  onKey(ev) {
    if (document.querySelector('dialog[open]')) return; // los diálogos modales gestionan su teclado
    const key = ev.key.toLowerCase();
    let handled = true;
    if (ev.ctrlKey && key === 'o') this.openPdfDialog();
    else if (ev.ctrlKey && key === 'f4') this.close(this.current); // Ctrl+W queda para «ajustar al ancho» del visor
    else if (ev.ctrlKey && key === 'tab') this.cycle(ev.shiftKey ? -1 : 1);
    else handled = Boolean(this.get(this.current)?.instance?.onKey?.(ev));
    if (handled) ev.preventDefault();
  }

  // ── Menús de la cabecera ───────────────────────────────────────────────
  brandMenu() {
    const items = [{ label: 'Abrir PDF (Ctrl+O)', icon: 'folder-open', onSelect: () => this.openPdfDialog() }, 'separator'];
    let section = 0;
    for (const tool of TOOLS) {
      if ((tool.section ?? 0) !== section) {
        items.push('separator');
        section = tool.section ?? 0;
      }
      items.push({ label: tool.menuLabel, icon: tool.icon, onSelect: () => this.open(tool.key) });
    }
    items.push('separator', { label: 'Alternar tema claro / oscuro', icon: 'moon', onSelect: this.toggleTheme });
    return items;
  }

  tabsMenu() {
    return this.tabs.map((tab) => ({
      label: `${tab.modified ? MODIFIED_MARK : ''}${tab.title}`, icon: tab.key === this.current ? 'check' : null,
      onSelect: () => this.activate(tab.key),
    }));
  }

  /** Menú contextual de una pestaña (como _show_tab_context_menu en Qt). */
  tabContextMenu(key) {
    const keys = this.tabs.filter((t) => t.closable).map((t) => t.key);
    const index = keys.indexOf(key);
    const { path } = this.get(key); // se lee al abrir el menú: puede cambiar con «Guardar como»
    const items = [
      { label: 'Cerrar pestaña', icon: 'x', onSelect: () => this.close(key) },
      { label: 'Cerrar las otras pestañas', icon: 'x', onSelect: () => this.closeMany(keys.filter((k) => k !== key)) },
      { label: 'Cerrar pestañas a la derecha', icon: 'arrow-right', onSelect: () => this.closeMany(keys.slice(index + 1)) },
    ];
    if (path) {
      items.push('separator',
        {
          label: 'Copiar ruta del archivo', icon: 'copy',
          onSelect: () => navigator.clipboard.writeText(path).then(() => setStatus('Ruta copiada al portapapeles')),
        },
        { label: 'Abrir carpeta en el Explorador', icon: 'folder', onSelect: () => call('documents.reveal', path) });
    }
    return items;
  }
}

export const shell = new Shell();
