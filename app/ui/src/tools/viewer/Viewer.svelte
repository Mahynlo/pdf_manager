<!--
  Pestaña de visor PDF: compone las barras
  de herramientas, las miniaturas, el lienzo (con la selección de texto y las
  anotaciones) y el panel lateral (índice, OCR, censura, IA y búsqueda).

  El lienzo y sus capas son código imperativo (canvas/canvas.ts, canvas/selection.ts,
  annotations/annotations.ts, annotations/editing.ts) sobre EmbedPDF. Este componente los
  crea, los coloca en la página y conecta sus avisos con el resto de la interfaz. Qué hay en
  cada carpeta: README.md.

  La abre el shell con la información de `viewer.open`. `close()` cierra la pestaña
  (acción «Cerrar documento») y `update(info)` avisa de que cambió el documento
  (cambios sin guardar, ruta tras «Guardar como»).
-->
<script lang="ts">
  import { onDestroy, onMount, tick, untrack } from 'svelte';
  import { call } from '$lib/api.ts';
  import Icon from '$lib/Icon.svelte';
  import type { MenuItem } from '$lib/menu.svelte.ts';
  import type { DocumentInfo } from '$lib/types.ts';
  import { openModal, setStatus, toast } from '$lib/ui.ts';
  import { viewport } from '$lib/viewport.svelte.ts';
  import { t, tip } from '$texts';
  import type { Annot } from './annotations/annotations.ts';
  import AiPanel from './panels/AiPanel.svelte';
  import { Annotations } from './annotations/annotations.ts';
  import { PageCanvas, TOOLS } from './canvas/canvas.ts';
  import { AnnotationEditor } from './annotations/editing.ts';
  import { MODES, type Mode } from './canvas/layout.ts';
  import OcrPanel from './ocr/OcrPanel.svelte';
  import { DocumentActions } from './document/operations.ts';
  import { printPdf, release as releasePrint } from './document/print.ts';
  import PropertiesDialog from './document/PropertiesDialog.svelte';
  import RedactPanel from './redact/RedactPanel.svelte';
  import { RedactionMarks } from './redact/redaction.ts';
  import SearchPanel from './panels/SearchPanel.svelte';
  import Thumbnails from './panels/Thumbnails.svelte';
  import StampsPanel from './stamps/StampsPanel.svelte';
  import { TextSelection } from './canvas/selection.ts';
  import TocTree from './panels/TocTree.svelte';
  import Toolbar from './toolbars/Toolbar.svelte';
  import ToolsBar from './toolbars/ToolsBar.svelte';

  const T = t.viewer;
  const INPUTS = 'input, textarea, select, [contenteditable]';
  const EDIT_TOOLS = new Set<string>([TOOLS.POINTER, TOOLS.SELECT, TOOLS.HAND]); // en las demás se dibuja
  const THUMBS_DELAY = 300; // ms tras un cambio de anotaciones antes de rehacer su miniatura
  // Paneles laterales en la barra vertical, por grupos: navegar, editar el documento y asistente.
  type DockTab = keyof typeof T.dock;
  const DOCK_GROUPS: { key: DockTab; icon: string }[][] = [
    [{ key: 'search', icon: 'search' }, { key: 'toc', icon: 'list-tree' }],
    [{ key: 'stamps', icon: 'stamp' }, { key: 'redact', icon: 'eraser' }, { key: 'ocr', icon: 'scan-text' }],
    [{ key: 'ai', icon: 'sparkles' }],
  ];

  /**
   * `info`: el documento abierto (`viewer.open`); `close()`: cerrar la pestaña; `update(info)`:
   * cambió el documento (cambios sin guardar, ruta tras «Guardar como»).
   */
  let { info, close, update }: {
    info: DocumentInfo;
    close: () => void;
    update: (info: DocumentInfo) => void;
  } = $props();
  const doc = untrack(() => info); // el documento se abre una vez; los cambios llegan por `actions`
  const docId = doc.id;

  // ── Estado que pinta la interfaz ───────────────────────────────────────
  let view = $state({
    page: 0, count: doc.pages.length, zoom: 1, mode: MODES.CONTINUOUS as Mode,
    canUndo: false, canRedo: false, night: false, sidebar: !viewport.narrow && !viewport.reading, dock: false, tools: !viewport.reading,
  });
  // Con el dedo, arrastrar tiene que desplazar la página: seleccionar texto hay que pedirlo.
  let tool = $state<string>(viewport.touch ? TOOLS.HAND : TOOLS.SELECT);
  let dockTab = $state<DockTab>('toc');
  let toc = $state.raw(doc.toc);
  let revision = $state(0); // cambia con cada operación sobre las páginas
  let versions = $state.raw<Record<number, number>>({}); // página -> cambios de sus anotaciones (rehacer su miniatura)

  let stage: HTMLDivElement;
  let toolbar = $state<Toolbar>();
  let search = $state<SearchPanel>();
  let ocr = $state<OcrPanel>();
  let redact = $state<RedactPanel>();
  let stamps = $state<StampsPanel>();
  let ai = $state<AiPanel>();

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
  if (viewport.narrow || viewport.reading) canvas.fitWidth(); // al 100 % no se vería la página entera
  const total = () => canvas.pageCount;
  const goTo = (index: number) => canvas.scrollToPage(Math.max(0, Math.min(total() - 1, index)));
  const thumbSelected = (index: number) => {
    if (viewport.compact) view.sidebar = false;
    goTo(index);
  };

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
      ai!.explain(text);
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
      search!.refresh();
      ocr!.refresh();
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
  let touched = new Set<number>();
  let thumbsTimer = 0;
  function refreshThumbs(pages: number[]) {
    for (const page of pages) touched.add(page);
    clearTimeout(thumbsTimer);
    thumbsTimer = window.setTimeout(() => {
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
  function showMark(mark: Annot) {
    leavePanel();
    canvas.scrollToRect(mark.pageIndex, canvas.toView(mark.pageIndex, mark.rect));
    if (!EDIT_TOOLS.has(tool)) setTool(TOOLS.POINTER);
    annotations.select([mark]);
  }

  // ── Acciones ───────────────────────────────────────────────────────────
  function setTool(next: string) {
    if (!EDIT_TOOLS.has(next)) leavePanel(); // se va a dibujar en la página
    if (next !== TOOLS.SELECT) selection.clear();
    if (!EDIT_TOOLS.has(next)) editor.clear();
    canvas.setTool(next);
    tool = next;
  }

  /** Color de la paleta: lo usan las siguientes anotaciones y, como en Qt, también recolorea las seleccionadas. */
  function setColor(color: string) {
    Object.assign(annotations.style, { penColor: color, shapeColor: color, highlightColor: color });
    if (editor.items.length) editor.setColor(color);
    canvas.setTool(canvas.tool); // la herramienta activa toma el color nuevo
  }

  /** Panel de sellos (0) o de firmas (1). */
  function openStamps(index: number) {
    openDockTab('stamps');
    stamps!.show(index);
  }

  /** Imprimir: el diálogo de WebView2 con el PDF y sus anotaciones tal como están en el visor. */
  async function print() {
    setStatus(T.print.preparing);
    try {
      await printPdf(await annotations.printCopy());
    } catch (err) {
      toast(T.print.error((err as Error).message), 'danger');
    }
  }

  async function showProperties() {
    try {
      openModal(PropertiesDialog, await call('viewer.properties', docId));
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  /** En el móvil el panel tapa la página: se cierra al ir a ella. */
  function leavePanel() {
    if (viewport.compact) view.dock = false;
  }

  function openDockTab(key: DockTab) {
    if (viewport.compact) view.sidebar = false;
    view.dock = true;
    dockTab = key;
  }

  /** Barra vertical: abre el panel o, si es el que ya se ve, lo cierra. */
  function toggleDockTab(key: DockTab) {
    if (view.dock && dockTab === key) view.dock = false;
    else openDockTab(key);
  }

  /** Ctrl+F, botón de la barra o «Buscar en el documento» de la selección. */
  async function openSearch(text: string | null = null) {
    openDockTab('search');
    if (text) search!.setQuery(text);
    await tick(); // el panel debe estar ya a la vista para recibir el foco
    search!.focus();
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

  /** Lo que no cabe en la barra superior en una pantalla estrecha. */
  function hiddenControls(): MenuItem[] {
    if (!viewport.narrow) return [];
    const B = T.toolbar;
    const mode = (label: string, icon: string, value: Mode): MenuItem => ({
      label, icon, checked: view.mode === value, onSelect: () => canvas.setMode(value),
    });
    return [
      ...(viewport.compact ? [
        { label: tip(B.zoomIn), icon: 'plus', onSelect: () => canvas.zoomIn() },
        { label: tip(B.zoomOut), icon: 'minus', onSelect: () => canvas.zoomOut() },
      ] : []),
      { label: B.fitWidth, icon: 'rows', onSelect: () => canvas.fitWidth() },
      { label: B.fitPage, icon: 'file', onSelect: () => canvas.fitPage() },
      'separator',
      mode(B.continuous, 'rows', MODES.CONTINUOUS),
      mode(B.double, 'book-open', MODES.DOUBLE),
      mode(B.single, 'file', MODES.SINGLE),
      { label: B.night, icon: 'moon', checked: view.night, onSelect: toolbarActions.toggleNight },
      'separator',
      { label: tip(B.first), icon: 'chevrons-left', disabled: view.page <= 0, onSelect: () => goTo(0) },
      { label: tip(B.last), icon: 'chevrons-right', disabled: view.page >= view.count - 1, onSelect: () => goTo(total() - 1) },
      'separator',
    ];
  }

  // Al cambiar de tamaño (girar el móvil, estrechar la ventana) se recolocan las barras.
  $effect(() => {
    view.tools = !viewport.reading;
  });
  $effect(() => {
    view.sidebar = !viewport.narrow && !viewport.reading;
  });

  const toolbarActions = {
    moreMenu: (): MenuItem[] => {
      const [save, saveAs, ...rest] = actions.menuItems();
      return [
        save, saveAs,
        { label: tip(T.more.print), icon: 'printer', onSelect: print },
        { label: T.more.properties, icon: 'info', onSelect: showProperties },
        ...rest,
        'separator',
        ...hiddenControls(),
        { label: T.more.legends, icon: 'tag', onSelect: () => stamps!.manageLegends() },
        { label: T.more.close, icon: 'x', onSelect: close },
      ];
    },
    first: () => goTo(0),
    prev,
    next,
    last: () => goTo(total() - 1),
    goTo,
    zoomIn: () => canvas.zoomIn(),
    zoomOut: () => canvas.zoomOut(),
    setZoom: (z: number) => canvas.setZoom(z),
    fitWidth: () => canvas.fitWidth(),
    fitPage: () => canvas.fitPage(),
    setMode: (m: string) => canvas.setMode(m as Mode),
    toggleNight: () => {
      view.night = !view.night;
      canvas.setNight(view.night);
    },
    toggleSidebar: () => {
      view.sidebar = !view.sidebar;
      if (view.sidebar) leavePanel();
    },
    toggleTools: () => (view.tools = !view.tools),
    undo,
    redo,
    toggleDock: () => (view.dock = !view.dock),
  };

  // ── Atajos (ver Configuración → Atajos de teclado) ─────────────────────
  type Keys = Record<string, () => unknown>;
  const ctrlKeys: Keys = {
    '=': () => canvas.zoomIn(),
    '+': () => canvas.zoomIn(),
    '-': () => canvas.zoomOut(),
    0: () => canvas.setZoom(1),
    h: () => canvas.fitPage(),
    w: () => canvas.fitWidth(),
    g: () => toolbar!.focusPage(),
    s: () => actions.save(),
    p: () => print(),
    f: () => openSearch(),
    home: () => goTo(0),
    end: () => goTo(total() - 1),
  };
  const ctrlShiftKeys: Keys = {
    s: () => actions.saveAs(),
    '+': () => canvas.zoomIn(), // teclados en los que «+» va con Mayúsculas
  };
  // Ctrl+C, Ctrl+A y deshacer/rehacer son del lienzo solo fuera de los campos de texto.
  const ctrlCanvasKeys: Keys = {
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
  const plainKeys: Keys = {
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
  export function onKey(ev: KeyboardEvent): boolean {
    const key = ev.key.toLowerCase();
    const inField = Boolean((ev.target as Element | null)?.closest?.(INPUTS));
    // Esc termina de marcar para censurar (aunque la marca recién puesta esté seleccionada) y
    // cancela la colocación de un sello o una firma.
    if (key === 'escape' && !inField && (tool === TOOLS.REDACT || tool === TOOLS.PLACE || tool === TOOLS.PLACE_TEXT)) {
      setTool(TOOLS.SELECT);
      return true;
    }
    // Con anotaciones seleccionadas: Supr, Esc, Ctrl+D y flechas son para ellas.
    if (!inField && editor.onKey(ev)) return true;
    if (key === 'escape' && editor.stopTyping()) return true;
    if (key === 'f3' && !ev.ctrlKey && !ev.altKey) {
      if (!search!.step(ev.shiftKey ? -1 : 1)) openSearch();
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
    releasePrint();
    canvas.destroy();
    call('viewer.close_document', docId).catch(() => {});
  });
</script>

<div class="viewer">
  <Toolbar bind:this={toolbar} {view} actions={toolbarActions} />
  <ToolsBar {tool} {setTool} {setColor} visible={view.tools} stamps={() => openStamps(0)} signatures={() => openStamps(1)} />
  <div class="viewer__body">
    <Thumbnails {docId} count={view.count} current={view.page} {revision} {versions} visible={view.sidebar}
                fetchThumbs={(pages) => canvas.thumbnails(pages)} release={(url) => URL.revokeObjectURL(url)} onSelect={thumbSelected} onMove={(src, dst) => actions.move(dst, src)} />
    {#if viewport.compact && view.sidebar}
      <button class="viewer-scrim" type="button" aria-label={T.toolbar.thumbnails} onclick={() => (view.sidebar = false)}></button>
    {/if}
    <div class="viewer__stage" bind:this={stage}></div>
    <aside class="viewer-dock" hidden={!view.dock}>
      <div class="viewer-dock__panels">
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'toc'}>
          <div class="toc-panel__head">
            <span class="toc-panel__icon"><Icon name="list-tree" size={20} /></span>
            <h2 class="heading">{T.toc.title}</h2>
            <span class="grow"></span>
            <button class="btn btn--icon btn--sm" type="button" title={T.toc.close} aria-label={T.toc.close}
                    onclick={() => (view.dock = false)}><Icon name="x" /></button>
          </div>
          <TocTree {toc} onSelect={(index) => { leavePanel(); goTo(index); }} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'ocr'}>
          <OcrPanel bind:this={ocr} {canvas} {docId} page={view.page} active={view.dock && dockTab === 'ocr'}
                    close={() => (view.dock = false)} {setTool} orient={() => actions.fixOrientation()}
                    changed={async () => {
                      // EmbedPDF recibe el texto nuevo (invisible) para seleccionarlo; antes,
                      // Python recibe las anotaciones (se reabre su versión).
                      await actions.run(() => annotations.sync());
                      canvas.reload();
                      search!.refresh();
                    }} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'redact'}>
          <RedactPanel bind:this={redact} {docId} {marks} {tool} {setTool} close={() => (view.dock = false)}
                       show={showMark} commit={(fn) => actions.change(fn)} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'stamps'}>
          <StampsPanel bind:this={stamps} {canvas} {annotations} {tool} {setTool} active={view.dock && dockTab === 'stamps'}
                       close={() => (view.dock = false)} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'ai'}>
          <AiPanel bind:this={ai} {docId} active={view.dock && dockTab === 'ai'} close={() => (view.dock = false)}
                   redact={async (items) => {
                     openDockTab('redact');
                     for (const item of items) await redact!.addTerm(item.texto);
                   }} />
        </div>
        <div class="viewer-dock__panel" role="tabpanel" hidden={dockTab !== 'search'}>
          <SearchPanel bind:this={search} {canvas} close={() => (view.dock = false)} navigated={leavePanel}
                       redact={(query) => {
                         openDockTab('redact');
                         redact!.addTerm(query);
                       }} />
        </div>
      </div>
    </aside>
    <div class="viewer-rail" role="tablist" aria-orientation={viewport.compact ? 'horizontal' : 'vertical'} aria-label={T.toolbar.dock}>
      {#each DOCK_GROUPS as group, i (i)}
        {#if i}<span class="viewer-rail__sep" aria-hidden="true"></span>{/if}
        {#each group as { key, icon } (key)}
          {@const open = view.dock && dockTab === key}
          <button class="viewer-rail__tab" class:is-active={open} type="button" role="tab" aria-selected={open}
                  title={tip(T.dock[key])} aria-label={tip(T.dock[key])} onclick={() => toggleDockTab(key)}>
            <Icon name={icon} size={18} />
          </button>
        {/each}
      {/each}
    </div>
  </div>
</div>
