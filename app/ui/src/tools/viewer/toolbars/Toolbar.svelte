<!--
  Barra superior del visor (como _toolbar_mixin.py en Qt): menú ⋮ · navegación · zoom ·
  modos de vista · deshacer/rehacer · paneles y búsqueda · modo noche.
-->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { openMenu, type MenuItem } from '$lib/menu.svelte.ts';
  import { strip } from '$lib/strip.ts';
  import { viewport } from '$lib/viewport.svelte.ts';
  import { t, tip } from '$texts';
  import { MODES } from '../canvas/layout.ts';

  const T = t.viewer.toolbar;
  const ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 200, 300, 400];
  // Lo que se oculta en una pantalla estrecha (responsive.css): pasa al menú ⋮ (hiddenControls).
  const WIDE = 'tb-wide';
  const ZOOM = 'tb-zoom-group';

  /** Estado que pinta la barra. */
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
  }

  /** Lo que hace cada botón (`moreMenu()` da las entradas del menú ⋮). */
  interface ToolbarActions {
    moreMenu(): MenuItem[];
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
    undo(): void;
    redo(): void;
    toggleNight(): void;
    toggleSidebar(): void;
    toggleDock(): void;
    toggleTools(): void;
  }

  let { view, actions }: { view: ToolbarView; actions: ToolbarActions } = $props();

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

{#snippet separator(group = '')}<span class="tb-sep {group}" aria-hidden="true"></span>{/snippet}

<div class="viewer-toolbar" role="toolbar" aria-label={T.label} use:strip>
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
  {@render separator(WIDE)}
  {@render button('rows', T.continuous, () => actions.setMode(MODES.CONTINUOUS), { checked: view.mode === MODES.CONTINUOUS, group: WIDE })}
  {@render button('book-open', T.double, () => actions.setMode(MODES.DOUBLE), { checked: view.mode === MODES.DOUBLE, group: WIDE })}
  {@render button('file', T.single, () => actions.setMode(MODES.SINGLE), { checked: view.mode === MODES.SINGLE, group: WIDE })}
  {@render separator()}
  {@render button('undo', tip(T.undo), actions.undo, { disabled: !view.canUndo })}
  {@render button('redo', tip(T.redo), actions.redo, { disabled: !view.canRedo })}
  {@render separator()}
  {#if viewport.reading}
    {@render button('pencil', T.tools, actions.toggleTools, { checked: view.tools })}
  {/if}
  {@render button('panel-left', T.thumbnails, actions.toggleSidebar, { checked: view.sidebar })}
  {@render button('moon', T.night, actions.toggleNight, { checked: view.night, group: WIDE })}
  <span class="grow"></span>
  {@render button('panel-right', T.dock, actions.toggleDock, { checked: view.dock, group: 'tb-dock-toggle' })}
</div>
