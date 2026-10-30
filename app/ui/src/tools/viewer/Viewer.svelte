<!--
  Pestaña de visor PDF (equivale a src_qt/ui/viewer/pdf_viewer.py): compone las barras
  de herramientas, las miniaturas, el lienzo (con la selección de texto y las
  anotaciones) y el panel lateral (índice, OCR, censura, IA y búsqueda).

  El lienzo y sus capas son código imperativo (canvas.js, text.js, annotations.js,
  editing.js) sobre EmbedPDF. Este componente los crea, los coloca en la página y conecta
  sus avisos con el resto de la interfaz.

  La abre el shell con la información de `viewer.open`. `close()` cierra la pestaña
  (acción «Cerrar documento») y `update(info)` avisa de que cambió el documento
  (cambios sin guardar, ruta tras «Guardar como»).
-->
<script>
  import { onDestroy, onMount, tick, untrack } from 'svelte';
  import { call } from '$lib/api.js';
  import Icon from '$lib/Icon.svelte';
  import { openModal, toast } from '$lib/ui.js';
  import AiPanel from './AiPanel.svelte';
  import { Annotations } from './annotations.js';
  import { PageCanvas, TOOLS } from './canvas.js';
  import { AnnotationEditor } from './editing.js';
  import { MODES } from './layout.js';
  import OcrPanel from './OcrPanel.svelte';
  import { DocumentActions } from './operations.js';
  import PrintDialog from './PrintDialog.svelte';
  import PropertiesDialog from './PropertiesDialog.svelte';
  import RedactPanel from './RedactPanel.svelte';
  import { RedactionMarks } from './redaction.js';
  import SearchPanel from './SearchPanel.svelte';
  import Sidebar from './Sidebar.svelte';
  import { openLegendsManager, openStampsMenu } from './stamps.js';
  import { TextSelection } from './text.js';
  import TocTree from './TocTree.svelte';
  import Toolbar from './Toolbar.svelte';
  import ToolsBar from './ToolsBar.svelte';

  const INPUTS = 'input, textarea, select, [contenteditable]';
  const EDIT_TOOLS = new Set([TOOLS.POINTER, TOOLS.SELECT, TOOLS.HAND]); // en las demás se dibuja
  const THUMBS_DELAY = 300; // ms tras un cambio de anotaciones antes de rehacer su miniatura
  // Pestañas del panel lateral, en el orden de Qt.
  const DOCK_TABS = [
    { key: 'toc', label: 'Índice', icon: 'list-tree' },
    { key: 'ocr', label: 'OCR', icon: 'scan-text' },
    { key: 'redact', label: 'Censura', icon: 'eraser' },
    { key: 'ai', label: 'IA', icon: 'sparkles' },
    { key: 'search', label: 'Buscar', icon: 'search' },
  ];

  let { info, close, update } = $props();
  const doc = untrack(() => info); // el documento se abre una vez; los cambios llegan por `actions`
  const docId = doc.id;

  // ── Estado que pinta la interfaz ───────────────────────────────────────
  let view = $state({
    page: 0, count: doc.pages.length, zoom: 1, mode: MODES.CONTINUOUS,
    canUndo: false, canRedo: false, night: false, sidebar: true, dock: false,
  });
  let tool = $state(TOOLS.SELECT);
  let dockTab = $state('toc');
  let toc = $state.raw(doc.toc);
  let revision = $state(0); // cambia con cada operación sobre las páginas
  let versions = $state.raw({}); // página -> cambios de sus anotaciones (rehacer su miniatura)

  let stage;
  let toolbar = $state();
  let search = $state();
  let ocr = $state();
  let redact = $state();
  let ai = $state();

  // ── Lienzo y sus capas ─────────────────────────────────────────────────
  // Las páginas y miniaturas las dibuja EmbedPDF con la versión del documento que tiene Python.
  const canvas = new PageCanvas(docId, doc.pages, doc.keys, {
    onPage: (i) => (view.page = i),
    onZoom: (z) => {
      view.zoom = z;
      selection.placeBar();
      editor.placeBar();
    },
    onMode: (m) => (view.mode = m),
    onTool: (t) => annotations.applyStyle(t),
    onDocument: () => annotations.documentShown(),
  });
  const total = () => canvas.pageCount;
  const goTo = (index) => canvas.scrollToPage(Math.max(0, Math.min(total() - 1, index)));

  const selection = new TextSelection(canvas, {
    searchDocument: (text) => openSearch(text),
    markup(kind, parts) {
      annotations.markup(kind, parts);
      // Como en Qt: tras marcar con la herramienta, se vuelve a la selección de texto.
      if (canvas.tool !== TOOLS.SELECT) setTool(TOOLS.SELECT);
    },
    redact(text, parts) {
      openDockTab('redact');
      marks.addSelection(text, parts);
    },
    explain(text) {
      openDockTab('ai');
      ai.explain(text);
    },
  });

  const actions = new DocumentActions(doc, {
    page: () => canvas.current,
    sync: () => annotations.sync(),
    apply(next, page) {
      canvas.setPages(next.pages, next.keys);
      selection.reset();
      view.count = next.pages.length;
      revision++;
      versions = {};
      toc = next.toc;
      search.refresh();
      ocr.refresh();
      goTo(page);
      update(next);
      showHistory();
    },
  });

  // Deshacer y rehacer: primero lo de EmbedPDF (anotaciones); si no queda, las operaciones de
  // página (Python). Tras una operación de página EmbedPDF empieza un historial nuevo, así que
  // el orden se respeta: lo hecho después de girar o mover se deshace antes que eso.
  let history = { canUndo: false, canRedo: false }; // el de EmbedPDF
  function showHistory() {
    view.canUndo = history.canUndo || actions.canUndoPages;
    view.canRedo = history.canRedo || actions.canRedoPages;
  }
  function undo() {
    if (history.canUndo) annotations.undo();
    else if (actions.canUndoPages) actions.undoPages();
  }
  function redo() {
    if (history.canRedo) annotations.redo();
    else if (actions.canRedoPages) actions.redoPages();
  }

  // Miniaturas de las páginas cuyas anotaciones cambiaron (juntas, tras una pausa).
  let touched = new Set();
  let thumbsTimer = 0;
  function refreshThumbs(pages) {
    for (const page of pages) touched.add(page);
    clearTimeout(thumbsTimer);
    thumbsTimer = setTimeout(() => {
      const next = { ...versions };
      for (const page of touched) next[page] = (next[page] ?? 0) + 1;
      touched = new Set();
      versions = next;
    }, THUMBS_DELAY);
  }

  const annotations = new Annotations(canvas, docId, {
    onHistory: ({ canUndo, canRedo }) => {
      history = { canUndo, canRedo };
      showHistory();
    },
    onChanged: () => actions.annotationsChanged().then(() => update(actions.info)),
    onSelect: (items) => editor.setSelection(items),
    onRendered: refreshThumbs,
    setTool: (t) => setTool(t),
  });

  const editor = new AnnotationEditor(canvas, annotations);
  const marks = new RedactionMarks(annotations);

  /** Va a una marca de censura y la selecciona (para moverla o borrarla). */
  function showMark(mark) {
    canvas.scrollToRect(mark.pageIndex, canvas.toView(mark.pageIndex, mark.rect));
    if (!EDIT_TOOLS.has(tool)) setTool(TOOLS.POINTER);
    annotations.select([mark]);
  }

  // ── Acciones ───────────────────────────────────────────────────────────
  function setTool(next) {
    if (next !== TOOLS.SELECT) selection.clear();
    if (!EDIT_TOOLS.has(next)) editor.clear();
    canvas.setTool(next);
    tool = next;
  }

  /** Color de la paleta: lo usan las siguientes anotaciones y, como en Qt, también recolorea las seleccionadas. */
  function setColor(color) {
    Object.assign(annotations.style, { penColor: color, shapeColor: color, highlightColor: color });
    if (editor.items.length) editor.setColor(color);
    canvas.setTool(canvas.tool); // la herramienta activa toma el color nuevo
  }

  /** Inserta un sello o leyenda en el centro de la vista y lo deja seleccionado. */
  function insertStamp(stamp) {
    const at = canvas.viewCenter() ?? { index: canvas.current, x: 100, y: 100 };
    const created = annotations.stamp(stamp, at);
    if (!created.length) return;
    setTool(TOOLS.POINTER);
    annotations.select(created);
  }

  /** Imprimir: PDFium dibuja las páginas con las anotaciones tal como están en el visor. */
  async function print() {
    await annotations.commit();
    openModal(PrintDialog, {
      docId, current: canvas.current, sizes: canvas.sizes, render: (pages, dpi, gray) => canvas.pageImages(pages, dpi, gray),
    });
  }

  async function showProperties() {
    try {
      openModal(PropertiesDialog, await call('viewer.properties', docId));
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  function openDockTab(key) {
    view.dock = true;
    dockTab = key;
  }

  /** Ctrl+F, botón de la barra o «Buscar en el documento» de la selección. */
  async function openSearch(text = null) {
    openDockTab('search');
    if (text) search.setQuery(text);
    await tick(); // el panel debe estar ya a la vista para recibir el foco
    search.focus();
  }

  // En doble página se avanza de par en par (1-2 → 3-4).
  const next = () => {
    const step = canvas.step();
    const target = Math.floor(canvas.current / step) * step + step;
    if (target < total()) goTo(target);
  };
  const prev = () => {
    const step = canvas.step();
    const target = Math.floor(canvas.current / step) * step - step;
    if (target >= 0) goTo(target);
  };

  const toolbarActions = {
    moreMenu: () => {
      const [save, saveAs, ...rest] = actions.menuItems();
      return [
        save, saveAs,
        { label: 'Imprimir documento (Ctrl+P)', icon: 'printer', onSelect: print },
        { label: 'Propiedades del documento', icon: 'info', onSelect: showProperties },
        ...rest,
        'separator',
        { label: 'Gestionar Leyendas y Sellos...', icon: 'tag', onSelect: () => openLegendsManager(insertStamp) },
        { label: 'Cerrar documento', icon: 'x', onSelect: close },
      ];
    },
    first: () => goTo(0),
    prev,
    next,
    last: () => goTo(total() - 1),
    goTo,
    zoomIn: () => canvas.zoomIn(),
    zoomOut: () => canvas.zoomOut(),
    setZoom: (z) => canvas.setZoom(z),
    fitWidth: () => canvas.fitWidth(),
    fitPage: () => canvas.fitPage(),
    setMode: (m) => canvas.setMode(m),
    toggleNight: () => {
      view.night = !view.night;
      canvas.setNight(view.night);
    },
    toggleSidebar: () => (view.sidebar = !view.sidebar),
    undo,
    redo,
    search: () => openSearch(),
    ocr: () => openDockTab('ocr'),
    toggleDock: () => (view.dock = !view.dock),
  };

  // ── Atajos (ver Configuración → Atajos de teclado) ─────────────────────
  const ctrlKeys = {
    '=': () => canvas.zoomIn(),
    '+': () => canvas.zoomIn(),
    '-': () => canvas.zoomOut(),
    0: () => canvas.setZoom(1),
    h: () => canvas.fitPage(),
    w: () => canvas.fitWidth(),
    g: () => toolbar.focusPage(),
    s: () => actions.save(),
    p: () => print(),
    f: () => openSearch(),
    home: () => goTo(0),
    end: () => goTo(total() - 1),
  };
  const ctrlShiftKeys = {
    s: () => actions.saveAs(),
    '+': () => canvas.zoomIn(), // teclados en los que «+» va con Mayúsculas
  };
  // Ctrl+C, Ctrl+A y deshacer/rehacer son del lienzo solo fuera de los campos de texto.
  const ctrlCanvasKeys = {
    c: () => selection.copy(),
    a: () => {
      selection.selectPage();
      return true;
    },
    z: () => {
      undo();
      return true;
    },
    y: () => {
      redo();
      return true;
    },
  };
  const plainKeys = {
    escape: () => selection.clear(),
    t: () => setTool(TOOLS.TEXT),
    home: () => goTo(0),
    end: () => goTo(total() - 1),
    pageup: prev,
    pagedown: next,
    arrowup: prev,
    arrowleft: prev,
    arrowdown: next,
    arrowright: next,
  };

  /** Atajos del visor; solo llegan aquí cuando esta pestaña es la activa. */
  export function onKey(ev) {
    const key = ev.key.toLowerCase();
    const inField = Boolean(ev.target.closest?.(INPUTS));
    // Esc termina de marcar para censurar (aunque la marca recién puesta esté seleccionada).
    if (key === 'escape' && !inField && tool === TOOLS.REDACT) {
      setTool(TOOLS.SELECT);
      return true;
    }
    // Con anotaciones seleccionadas: Supr, Esc, Ctrl+D y flechas son para ellas.
    if (!inField && editor.onKey(ev)) return true;
    if (key === 'escape' && editor.stopTyping()) return true;
    if (key === 'f3' && !ev.ctrlKey && !ev.altKey) {
      if (!search.step(ev.shiftKey ? -1 : 1)) openSearch();
      return true;
    }
    if (ev.ctrlKey && !ev.altKey && ev.shiftKey && key === 'z') return !inField && Boolean(ctrlCanvasKeys.y());
    if (ev.ctrlKey && !ev.altKey && !ev.shiftKey && key in ctrlCanvasKeys) {
      return !inField && Boolean(ctrlCanvasKeys[key]());
    }
    if (ev.ctrlKey && !ev.altKey) {
      const keys = ev.shiftKey ? ctrlShiftKeys : ctrlKeys;
      keys[key]?.();
      return key in keys;
    }
    // Las teclas sin modificador son para el campo de texto que tenga el foco.
    if (ev.ctrlKey || ev.altKey || inField) return false;
    plainKeys[key]?.();
    return key in plainKeys;
  }

  export function onShow() {
    canvas.el.focus({ preventScroll: true });
  }

  export function canClose() {
    return actions.canClose();
  }

  // La barra flotante de la selección y la de anotaciones se colocan sobre el lienzo.
  onMount(() => {
    stage.append(canvas.el, selection.bar, editor.bar);
    canvas.setTool(tool);
    canvas.scrollToPage(0);
  });

  onDestroy(() => {
    clearTimeout(thumbsTimer);
    canvas.destroy();
    call('viewer.close_document', docId).catch(() => {});
  });
</script>

<div class="viewer">
  <Toolbar bind:this={toolbar} {view} actions={toolbarActions} />
  <ToolsBar {tool} {setTool} {setColor} stamps={(button) => openStampsMenu(button, insertStamp)} />
  <div class="viewer__body">
    <Sidebar {docId} count={view.count} current={view.page} {revision} {versions} visible={view.sidebar}
             fetchThumbs={(pages) => canvas.thumbnails(pages)} release={(url) => URL.revokeObjectURL(url)} onSelect={goTo} onMove={(src, dst) => actions.move(dst, src)} />
    <div class="viewer__stage" bind:this={stage}></div>
    <aside class="viewer-dock" hidden={!view.dock}>
      <div class="viewer-dock__bar" role="tablist">
        {#each DOCK_TABS as { key, label, icon } (key)}
          <button class="viewer-dock__tab" class:is-active={dockTab === key} type="button" role="tab"
                  aria-selected={dockTab === key} onclick={() => (dockTab = key)}>
            <Icon name={icon} size={15} />{label}
          </button>
        {/each}
      </div>
      <div class="viewer-dock__panels">
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'toc'}>
          <TocTree {toc} onSelect={goTo} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'ocr'}>
          <OcrPanel bind:this={ocr} {canvas} {docId} page={view.page} active={view.dock && dockTab === 'ocr'}
                    close={() => (view.dock = false)} {setTool} orient={() => actions.fixOrientation()}
                    changed={async () => {
                      // EmbedPDF recibe el texto nuevo (invisible) para seleccionarlo; antes,
                      // Python recibe las anotaciones (se reabre su versión).
                      await actions.run(() => annotations.sync());
                      canvas.reload();
                      search.refresh();
                    }} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'redact'}>
          <RedactPanel bind:this={redact} {docId} {marks} {tool} {setTool} close={() => (view.dock = false)}
                       show={showMark} commit={(fn) => actions.change(fn)} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'ai'}>
          <AiPanel bind:this={ai} {docId} active={view.dock && dockTab === 'ai'} close={() => (view.dock = false)}
                   redact={async (items) => {
                     openDockTab('redact');
                     for (const item of items) await redact.addTerm(item.texto);
                   }} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'search'}>
          <SearchPanel bind:this={search} {canvas} close={() => (view.dock = false)}
                       redact={(query) => {
                         openDockTab('redact');
                         redact.addTerm(query);
                       }} />
        </div>
      </div>
    </aside>
  </div>
</div>
