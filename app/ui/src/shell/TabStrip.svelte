<!--
  Las pestañas de la cabecera (patrón «tabs» de WAI-ARIA). Si no caben, la tira se desplaza con la
  rueda, deslizando el dedo o con las flechas de los lados (con ratón), y difumina el borde por el
  que siguen. Se reordenan arrastrándolas (con el dedo, tras mantenerlas pulsadas: tab-drag.ts),
  con Ctrl+Shift+Re Pág / Av Pág o desde su menú. Teclado: ← → Inicio Fin van de una a otra.
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { flip } from 'svelte/animate';
  import Icon from '$lib/Icon.svelte';
  import { openMenuAt } from '$lib/menu.svelte.ts';
  import { scrollStrip, strip, type Overflow } from '$lib/strip.ts';
  import { shell } from './shell.svelte.ts';
  import { TabDrag } from './tab-drag.ts';
  import { t, tip } from '$texts';

  const T = t.shell.header;
  const REORDER_MS = 150;

  let bar = $state<HTMLDivElement>();
  let overflow = $state<Overflow>({ start: false, end: false });
  let dragging = $state<string | null>(null);

  const scrollable = $derived(overflow.start || overflow.end);
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');

  $effect(() => {
    if (!bar) return;
    const drag = new TabDrag({
      strip: bar,
      movable: (key) => shell.movable(key),
      move: async (key, index) => {
        shell.moveTab(key, index);
        await tick();
      },
      menu: (key, x, y) => showMenu(key, x, y),
      dragging: (key) => (dragging = key),
    });
    return drag.attach();
  });

  // La pestaña activa siempre a la vista: al cambiar de pestaña y al cambiar de tamaño la tira.
  $effect(() => {
    void shell.current;
    tick().then(revealActive);
  });
  $effect(() => {
    if (!bar) return;
    const resize = new ResizeObserver(revealActive);
    resize.observe(bar);
    return () => resize.disconnect();
  });

  function revealActive() {
    bar?.querySelector('.tab.is-active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function showMenu(key: string, x: number, y: number) {
    if (shell.get(key)?.closable) openMenuAt(x, y, shell.tabContextMenu(key));
  }

  function onContextMenu(ev: MouseEvent, key: string) {
    ev.preventDefault();
    showMenu(key, ev.clientX, ev.clientY);
  }

  /** Teclado de una pestaña: activar, ir a otra (activándola) y moverla. */
  function onKey(ev: KeyboardEvent, key: string) {
    const keys = shell.tabs.map((tab) => tab.key);
    const at = keys.indexOf(key);
    const target = {
      ArrowLeft: at - 1, ArrowRight: at + 1, Home: 0, End: keys.length - 1,
    }[ev.key];
    if (ev.key === 'Enter' || ev.key === ' ') shell.activate(key);
    else if (ev.key === 'Delete') void shell.close(key);
    else if (target === undefined || ev.ctrlKey || ev.altKey) return;
    else {
      const next = keys[(target + keys.length) % keys.length];
      shell.activate(next);
      tick().then(() => bar?.querySelector<HTMLElement>(`[data-key="${CSS.escape(next)}"]`)?.focus());
    }
    ev.preventDefault();
  }
</script>

<div class="tabstrip" class:is-scrollable={scrollable}>
  <button class="tabstrip__scroll" type="button" title={T.scrollTabsStart} aria-label={T.scrollTabsStart}
          tabindex="-1" disabled={!overflow.start} onclick={() => bar && scrollStrip(bar, -1)}>
    <Icon name="chevron-left" size={16} />
  </button>
  <div class="tabbar" role="tablist" aria-label={T.tabs} bind:this={bar}
       use:strip={{ onOverflow: (next) => (overflow = next) }}>
    {#each shell.tabs as tab (tab.key)}
      <div class="tab" class:is-closable={tab.closable} class:is-active={tab.key === shell.current}
           role="tab" tabindex={tab.key === shell.current ? 0 : -1} aria-selected={tab.key === shell.current}
           title={tab.path ?? tab.title} data-key={tab.key}
           animate:flip={{ duration: dragging === tab.key || reduceMotion.matches ? 0 : REORDER_MS }}
           onclick={() => shell.activate(tab.key)} onkeydown={(ev) => onKey(ev, tab.key)}
           onauxclick={(ev) => ev.button === 1 && shell.close(tab.key)} oncontextmenu={(ev) => onContextMenu(ev, tab.key)}>
        <Icon name={tab.icon} />
        <span class="ellipsis">{tab.label}</span>
        {#if tab.closable}
          <button class="tab__close" type="button" title={tip(T.closeTab)} aria-label={T.closeTab.label} tabindex="-1"
                  onclick={(ev) => { ev.stopPropagation(); shell.close(tab.key); }}>
            <Icon name="x" size={14} />
          </button>
        {/if}
      </div>
    {/each}
  </div>
  <button class="tabstrip__scroll" type="button" title={T.scrollTabsEnd} aria-label={T.scrollTabsEnd}
          tabindex="-1" disabled={!overflow.end} onclick={() => bar && scrollStrip(bar, 1)}>
    <Icon name="chevron-right" size={16} />
  </button>
</div>
