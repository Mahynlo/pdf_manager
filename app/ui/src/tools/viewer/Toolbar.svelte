<!--
  Barra superior del visor (como _toolbar_mixin.py en Qt): menú ⋮ · navegación · zoom ·
  modos de vista · deshacer/rehacer · paneles y búsqueda · modo noche.
-->
<script>
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.js';
  import { MODES } from './layout.js';

  const ZOOM_PRESETS = [25, 50, 75, 100, 125, 150, 200, 300, 400];

  /**
   * `view`: { page, count, zoom, mode, canUndo, canRedo, night, sidebar, dock } (lo pinta);
   * `actions`: { moreMenu(), first(), prev(), next(), last(), goTo(i), zoomIn(), zoomOut(),
   *   setZoom(z), fitWidth(), fitPage(), setMode(m), undo(), redo(), toggleNight(),
   *   toggleSidebar(), search(), ocr(), toggleDock() }
   */
  let { view, actions } = $props();

  let pageInput;
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

  function pageKey(ev) {
    if (ev.key === 'Enter') {
      // Al salir del campo las flechas y Av/Re Pág vuelven a pasar página.
      const page = parseInt(pageText, 10);
      pageInput.blur();
      if (Number.isFinite(page)) actions.goTo(page - 1);
    } else if (ev.key === 'Escape') {
      pageInput.blur();
    }
  }

  function zoomKey(ev) {
    if (ev.key !== 'Enter') return;
    const value = parseFloat(zoomText.replace('%', ''));
    if (Number.isFinite(value) && value > 0) actions.setZoom(value / 100);
    else zoomText = zoomLabel();
    ev.currentTarget.select();
  }

  function zoomMenu(ev) {
    openMenu(ev.currentTarget.parentElement, [
      ...ZOOM_PRESETS.map((pct) => ({
        label: `${pct}%`, checked: Math.round(view.zoom * 100) === pct, onSelect: () => actions.setZoom(pct / 100),
      })),
      'separator',
      { label: 'Ajustar Ancho', onSelect: actions.fitWidth },
      { label: 'Ajustar Página', onSelect: actions.fitPage },
    ]);
  }
</script>

{#snippet button(icon, title, onclick, { checked = undefined, disabled = false } = {})}
  <button class="btn btn--icon tb-btn" class:is-checked={checked} type="button" {title} aria-label={title}
          aria-pressed={checked} {disabled} {onclick}>
    <Icon name={icon} size={18} />
  </button>
{/snippet}

{#snippet separator()}<span class="tb-sep" aria-hidden="true"></span>{/snippet}

<div class="viewer-toolbar" role="toolbar">
  {@render button('more-vertical', 'Más opciones y operaciones del documento', (ev) => openMenu(ev.currentTarget, actions.moreMenu()))}
  {@render separator()}
  {@render button('chevrons-left', 'Primera página (Inicio)', actions.first, { disabled: view.page <= 0 })}
  {@render button('chevron-left', 'Página anterior (Re Pág / ←)', actions.prev, { disabled: view.page <= 0 })}
  <input bind:this={pageInput} bind:value={pageText} class="input tb-page" type="text" inputmode="numeric"
         title="Ir a página específica (Ctrl+G)" onkeydown={pageKey}
         onfocus={() => { editingPage = true; pageInput.select(); }}
         onblur={() => { editingPage = false; pageText = String(view.page + 1); }} />
  <span class="tb-total muted">/ {view.count}</span>
  {@render button('chevron-right', 'Página siguiente (Av Pág / →)', actions.next, { disabled: view.page >= view.count - 1 })}
  {@render button('chevrons-right', 'Última página (Fin)', actions.last, { disabled: view.page >= view.count - 1 })}
  {@render separator()}
  {@render button('minus', 'Reducir zoom (Ctrl -)', actions.zoomOut)}
  <div class="tb-zoom">
    <input bind:value={zoomText} class="tb-zoom__input" type="text" title="Nivel de zoom" aria-label="Nivel de zoom"
           onkeydown={zoomKey} onfocus={(ev) => { editingZoom = true; ev.currentTarget.select(); }}
           onblur={() => { editingZoom = false; zoomText = zoomLabel(); }} />
    <button class="tb-zoom__menu" type="button" title="Niveles de zoom" aria-label="Niveles de zoom" onclick={zoomMenu}>
      <Icon name="chevron-down" size={14} />
    </button>
  </div>
  {@render button('plus', 'Aumentar zoom (Ctrl +)', actions.zoomIn)}
  {@render separator()}
  {@render button('rows', 'Scroll continuo', () => actions.setMode(MODES.CONTINUOUS), { checked: view.mode === MODES.CONTINUOUS })}
  {@render button('book-open', 'Doble página (la rueda pasa de par en par)', () => actions.setMode(MODES.DOUBLE), { checked: view.mode === MODES.DOUBLE })}
  {@render button('file', 'Página única (la rueda pasa de página)', () => actions.setMode(MODES.SINGLE), { checked: view.mode === MODES.SINGLE })}
  {@render separator()}
  {@render button('undo', 'Deshacer (Ctrl+Z)', actions.undo, { disabled: !view.canUndo })}
  {@render button('redo', 'Rehacer (Ctrl+Y)', actions.redo, { disabled: !view.canRedo })}
  {@render separator()}
  {@render button('scan-text', 'Ejecutar OCR en la página actual', actions.ocr)}
  {@render button('panel-left', 'Mostrar/Ocultar miniaturas', actions.toggleSidebar, { checked: view.sidebar })}
  {@render button('search', 'Buscar en el documento (Ctrl+F)', actions.search)}
  {@render separator()}
  {@render button('moon', 'Modo noche (Invertir colores del lienzo)', actions.toggleNight, { checked: view.night })}
  <span class="grow"></span>
  {@render button('panel-right', 'Expandir/Colapsar panel lateral', actions.toggleDock, { checked: view.dock })}
</div>
