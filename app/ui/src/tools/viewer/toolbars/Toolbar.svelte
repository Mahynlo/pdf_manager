<!--
  Barra superior del visor (como _toolbar_mixin.py en Qt): menú ⋮ · navegación · zoom ·
  mano, selección de texto y puntero · modos de vista · deshacer/rehacer · «Anotar» (abre la
  barra de anotaciones, ToolsBar.svelte) · menús «Páginas» y «Exportar» · paneles · modo noche.
-->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { fit } from '$lib/fit.ts';
  import { openMenu, type MenuItem } from '$lib/menu.svelte.ts';
  import { strip } from '$lib/strip.ts';
  import { t, tip } from '$texts';
  import { TOOLS } from '../canvas/canvas.ts';
  import { MODES } from '../canvas/layout.ts';

  const T = t.viewer.toolbar;
  const TT = t.viewer.tools;
  const NAVIGATE = [
    { key: TOOLS.HAND, icon: 'hand', title: TT.hand },
    { key: TOOLS.SELECT, icon: 'text-cursor', title: TT.select },
    { key: TOOLS.POINTER, icon: 'pointer', title: TT.pointer },
  ];
  // En el móvil van en un botón (responsive.css): la última usada y, en la flecha, las tres.
  let lastNavigate = $state(TOOLS.SELECT as string);
  $effect(() => {
    if (NAVIGATE.some((b) => b.key === tool)) lastNavigate = tool;
  });
  const shownNavigate = $derived(NAVIGATE.find((b) => b.key === lastNavigate) ?? NAVIGATE[1]);
  const ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 200, 300, 400];
  // Se compacta para caber (lib/fit.ts, `data-level` en styles/viewer.css):
  //   1  «Anotar», «Páginas» y «Exportar», solo con su icono;
  //   2  mano, selección y puntero en un botón; los menús, sin su flecha;
  //   3  sin primera/última página, modos de vista ni modo noche: pasan al menú ⋮ (`collapsed()`);
  //   4  tampoco «Páginas» ni «Exportar»: también al menú ⋮ (`menusCollapsed()`).
  const LEVELS = 4;
  let bar: HTMLDivElement;
  const level = () => Number(bar?.dataset.level ?? 0);
  /** Si los controles `tb-wide` no están en la barra (niveles 3 y 4): van al menú ⋮. */
  export function collapsed(): boolean {
    return level() >= 3;
  }
  /** Si «Páginas» y «Exportar» no están en la barra (nivel 4): sus entradas van al menú ⋮. */
  export function menusCollapsed(): boolean {
    return level() >= 4;
  }
  // Lo que se oculta en una pantalla estrecha (responsive.css): pasa al menú ⋮ (hiddenControls).
  const WIDE = 'tb-wide';
  const ZOOM = 'tb-zoom-group';
  const MENUS = 'tb-menus';
  const PHONE_HIDDEN = 'tb-phone-hidden';

  /** Estado que pinta la barra (`tools`: la barra de anotaciones abierta). */
  interface ToolbarView {
    page: number;
    count: number;
    zoom: number;
    mode: string;
    canUndo: boolean;
    canRedo: boolean;
    night: boolean;
    sidebar: boolean;
    dock: boolean;
    tools: boolean;
    forms: boolean;
  }

  /** Lo que hace cada botón (`moreMenu()` da las entradas del menú ⋮). */
  interface ToolbarActions {
    moreMenu(): MenuItem[];
    pagesMenu(): MenuItem[];
    exportMenu(): MenuItem[];
    first(): void;
    prev(): void;
    next(): void;
    last(): void;
    goTo(page: number): void;
    zoomIn(): void;
    zoomOut(): void;
    setZoom(zoom: number): void;
    fitWidth(): void;
    fitPage(): void;
    setMode(mode: string): void;
    setTool(tool: string): void;
    undo(): void;
    redo(): void;
    toggleNight(): void;
    toggleSidebar(): void;
    toggleDock(): void;
    toggleTools(): void;
    toggleForms(): void;
  }

  /** `tool`: la herramienta activa del lienzo. */
  let { view, tool, actions }: { view: ToolbarView; tool: string; actions: ToolbarActions } = $props();

  let pageInput: HTMLInputElement;
  let pageText = $state('1');
  let zoomText = $state('100%');
  let editingPage = false;
  let editingZoom = false;

  const zoomLabel = () => `${Math.round(view.zoom * 100)}%`;

  // Los campos muestran la página y el zoom actuales salvo mientras se escribe en ellos.
  $effect(() => {
    const text = String(view.page + 1);
    if (!editingPage) pageText = text;
  });
  $effect(() => {
    const text = zoomLabel();
    if (!editingZoom) zoomText = text;
  });

  export function focusPage() {
    pageInput.focus();
    pageInput.select();
  }

  function pageKey(ev: KeyboardEvent) {
    if (ev.key === 'Enter') {
      // Al salir del campo las flechas y Av/Re Pág vuelven a pasar página.
      const page = parseInt(pageText, 10);
      pageInput.blur();
      if (Number.isFinite(page)) actions.goTo(page - 1);
    } else if (ev.key === 'Escape') {
      pageInput.blur();
    }
  }

  function zoomKey(ev: KeyboardEvent & { currentTarget: HTMLInputElement }) {
    if (ev.key !== 'Enter') return;
    const value = parseFloat(zoomText.replace('%', ''));
    if (Number.isFinite(value) && value > 0) actions.setZoom(value / 100);
    else zoomText = zoomLabel();
    ev.currentTarget.select();
  }

  function navigateMenu(ev: MouseEvent & { currentTarget: HTMLButtonElement }) {
    openMenu(ev.currentTarget.parentElement!, NAVIGATE.map(({ key, icon, title }) => ({
      label: title, icon, checked: tool === key, onSelect: () => actions.setTool(key),
    })));
  }

  function zoomMenu(ev: MouseEvent & { currentTarget: HTMLButtonElement }) {
    openMenu(ev.currentTarget.parentElement!, [
      ...ZOOM_PRESETS.map((pct) => ({
        label: `${pct}%`, checked: Math.round(view.zoom * 100) === pct, onSelect: () => actions.setZoom(pct / 100),
      })),
      'separator',
      { label: T.fitWidth, onSelect: actions.fitWidth },
      { label: T.fitPage, onSelect: actions.fitPage },
    ]);
  }
</script>

{#snippet button(icon: string, title: string, onclick: (ev: MouseEvent & { currentTarget: HTMLButtonElement }) => void,
                 { checked = undefined, disabled = false, group = '' }: { checked?: boolean; disabled?: boolean; group?: string } = {})}
  <button class="btn btn--icon tb-btn {group}" class:is-checked={checked} type="button" {title} aria-label={title}
          aria-pressed={checked} {disabled} {onclick}>
    <Icon name={icon} size={18} />
  </button>
{/snippet}

<!-- Botón con menú («Páginas», «Exportar»); en el móvil, sus entradas van al menú ⋮. -->
{#snippet menuButton(icon: string, label: string, title: string, items: () => MenuItem[])}
  <button class="btn btn--ghost tb-btn tb-annotate tb-menu-btn {MENUS}" type="button" {title} aria-label={title}
          aria-haspopup="menu" onclick={(ev) => openMenu(ev.currentTarget, items())}>
    <Icon name={icon} size={18} /><span class="tb-annotate__label">{label}</span><span class="tb-menu-btn__arrow"><Icon name="chevron-down" size={12} /></span>
  </button>
{/snippet}

{#snippet separator(group = '')}<span class="tb-sep {group}" aria-hidden="true"></span>{/snippet}

<div bind:this={bar} class="viewer-toolbar viewer-toolbar--main" role="toolbar" aria-label={T.label}
     use:fit={{ levels: LEVELS }} use:strip>
  {@render button('more-vertical', T.more, (ev) => openMenu(ev.currentTarget, actions.moreMenu()))}
  {@render separator()}
  {@render button('chevrons-left', tip(T.first), actions.first, { disabled: view.page <= 0, group: WIDE })}
  {@render button('chevron-left', tip(T.prev), actions.prev, { disabled: view.page <= 0 })}
  <input bind:this={pageInput} bind:value={pageText} class="input tb-page" type="text" inputmode="numeric"
         title={tip(T.goToPage)} onkeydown={pageKey}
         onfocus={() => { editingPage = true; pageInput.select(); }}
         onblur={() => { editingPage = false; pageText = String(view.page + 1); }} />
  <span class="tb-total muted">/ {view.count}</span>
  {@render button('chevron-right', tip(T.next), actions.next, { disabled: view.page >= view.count - 1 })}
  {@render button('chevrons-right', tip(T.last), actions.last, { disabled: view.page >= view.count - 1, group: WIDE })}
  {@render separator(ZOOM)}
  {@render button('minus', tip(T.zoomOut), actions.zoomOut, { group: ZOOM })}
  <div class="tb-zoom tb-zoom-group">
    <input bind:value={zoomText} class="tb-zoom__input" type="text" title={T.zoomLevel} aria-label={T.zoomLevel}
           onkeydown={zoomKey} onfocus={(ev) => { editingZoom = true; ev.currentTarget.select(); }}
           onblur={() => { editingZoom = false; zoomText = zoomLabel(); }} />
    <button class="tb-zoom__menu" type="button" title={T.zoomLevels} aria-label={T.zoomLevels} onclick={zoomMenu}>
      <Icon name="chevron-down" size={14} />
    </button>
  </div>
  {@render button('plus', tip(T.zoomIn), actions.zoomIn, { group: ZOOM })}
  {@render separator()}
  <div class="tb-nav" role="group" aria-label={TT.groups.navigate}>
    {#each NAVIGATE as { key, icon, title } (key)}
      {@render button(icon, title, () => actions.setTool(key), { checked: tool === key })}
    {/each}
  </div>
  <div class="tb-split tb-nav-split" class:is-checked={tool === shownNavigate.key}>
    {@render button(shownNavigate.icon, shownNavigate.title, () => actions.setTool(shownNavigate.key), { checked: tool === shownNavigate.key })}
    <button class="tb-split__more" type="button" title={TT.more(TT.groups.navigate)} aria-label={TT.more(TT.groups.navigate)}
            aria-haspopup="menu" onclick={navigateMenu}>
      <Icon name="chevron-down" size={12} />
    </button>
  </div>
  {@render separator(WIDE)}
  {@render button('rows', T.continuous, () => actions.setMode(MODES.CONTINUOUS), { checked: view.mode === MODES.CONTINUOUS, group: WIDE })}
  {@render button('book-open', T.double, () => actions.setMode(MODES.DOUBLE), { checked: view.mode === MODES.DOUBLE, group: WIDE })}
  {@render button('file', T.single, () => actions.setMode(MODES.SINGLE), { checked: view.mode === MODES.SINGLE, group: WIDE })}
  {@render separator()}
  {@render button('undo', tip(T.undo), actions.undo, { disabled: !view.canUndo })}
  {@render button('redo', tip(T.redo), actions.redo, { disabled: !view.canRedo })}
  <!-- En el móvil, «Anotar» va en la barra de abajo (Viewer.svelte) y las miniaturas en ⋮ → Vista. -->
  {@render separator(PHONE_HIDDEN)}
  <button class="btn btn--ghost tb-btn tb-annotate {PHONE_HIDDEN}" class:is-checked={view.tools} type="button" title={T.tools}
          aria-label={T.tools} aria-pressed={view.tools} onclick={actions.toggleTools}>
    <Icon name="pen-line" size={18} /><span class="tb-annotate__label">{T.annotate}</span>
  </button>
  <button class="btn btn--ghost tb-btn tb-annotate {PHONE_HIDDEN}" class:is-checked={view.forms} type="button" title={T.formsTip}
          aria-label={T.formsTip} aria-pressed={view.forms} onclick={actions.toggleForms}>
    <Icon name="text-cursor-input" size={18} /><span class="tb-annotate__label">{T.forms}</span>
  </button>
  {@render menuButton('files', T.pages, T.pagesTip, actions.pagesMenu)}
  {@render menuButton('download', T.export, T.exportTip, actions.exportMenu)}
  {@render separator(MENUS)}
  {@render button('panel-left', T.thumbnails, actions.toggleSidebar, { checked: view.sidebar, group: PHONE_HIDDEN })}
  {@render button('moon', T.night, actions.toggleNight, { checked: view.night, group: WIDE })}
  <span class="grow"></span>
  {@render button('panel-right', T.dock, actions.toggleDock, { checked: view.dock, group: 'tb-dock-toggle' })}
</div>
