<!--
  Herramienta Ayuda: las guías de src/assets/ayuda/ (el servicio `help` las da en HTML seguro, con
  su título, icono, resumen e índice) y los atajos de teclado (la lista de Configuración).

  A la izquierda, el buscador y las guías (la abierta, con su índice: se marca la sección que se
  está leyendo); a la derecha, la guía, con «Anterior» y «Siguiente» al final. Las imágenes se
  amplían al pulsarlas. Enlaces dentro de una guía:
    [texto](#seccion)        una sección de la misma guía
    [texto](ayuda:visor)     otra guía (la primera cuyo archivo contiene «visor»; ayuda:atajos, los atajos)
    [texto](https://…)       en el navegador
-->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { Tool } from '../../shell/tools.ts';

  /** Guía de `help.documents`. */
  interface Guide {
    file: string;
    title: string;
    icon: string;
    summary: string;
  }

  /** Guía abierta (`help.document`). */
  interface GuideDoc extends Guide {
    html: string;
    sections: { id: string; title: string }[];
  }

  /** Resultado de `help.search`. */
  interface Hit {
    file: string;
    guide: string;
    section: string;
    title: string;
    snippet: string;
  }

  const T = t.help;
  const SHORTCUTS = 'atajos'; // la guía de los atajos (no es un archivo)
  const STORE = 'help-guide'; // la última guía abierta (este navegador)

  let { tool }: { tool: Tool } = $props();

  let guides = $state<Guide[] | null>(null);
  let active = $state('');
  let doc = $state<GuideDoc | null>(null);
  let current = $state(''); // sección que se está leyendo
  let query = $state('');
  let hits = $state<Hit[] | null>(null);
  let navOpen = $state(false); // pantalla estrecha: la lista de guías, desplegada
  let zoomed = $state<{ src: string; alt: string } | null>(null);
  let main: HTMLElement;

  const shortcutsGuide: Guide = { file: SHORTCUTS, title: T.shortcuts.title, icon: T.shortcuts.icon, summary: T.shortcuts.summary };
  const all = $derived([...(guides ?? []), shortcutsGuide]);
  const index = $derived(all.findIndex((g) => g.file === active));
  const shown = $derived(active === SHORTCUTS ? { ...shortcutsGuide, html: '', sections: [] } : doc);

  function remember(file: string) {
    try {
      localStorage.setItem(STORE, file);
    } catch {
      // sin almacenamiento (ventana privada…): se abre la primera
    }
  }

  function remembered(): string | null {
    try {
      return localStorage.getItem(STORE);
    } catch {
      return null;
    }
  }

  /** Abre la guía `file` y, si se da, va a su sección `section`. */
  async function open(file: string, section = '') {
    navOpen = false;
    if (file !== active || (file !== SHORTCUTS && !doc)) {
      try {
        doc = file === SHORTCUTS ? null : await call<GuideDoc>('help.document', file);
      } catch (err) {
        toast((err as Error).message, 'danger');
        return;
      }
      active = file;
      current = '';
      remember(file);
    }
    requestAnimationFrame(() => (section ? goTo(section) : main?.scrollTo({ top: 0 })));
  }

  let picked = ''; // la última sección pulsada en el índice

  function goTo(id: string) {
    const target = main?.querySelector<HTMLElement>(`#${CSS.escape(id)}`);
    if (!target) return;
    main.scrollTo({ top: target.offsetTop - 12, behavior: 'smooth' });
    current = picked = id;
  }

  // La sección que se lee: la última cuyo título ya pasó por arriba. Al final de la guía, las
  // últimas secciones no llegan arriba: vale la pulsada si se ve.
  function onscroll() {
    if (!shown?.sections.length) return;
    const top = main.scrollTop;
    let id = shown.sections[0].id;
    for (const { id: next } of shown.sections) {
      const heading = main.querySelector<HTMLElement>(`#${CSS.escape(next)}`);
      if (heading && heading.offsetTop - top <= 80) id = next;
    }
    if (top + main.clientHeight >= main.scrollHeight - 2) {
      const heading = picked && main.querySelector<HTMLElement>(`#${CSS.escape(picked)}`);
      id = heading && heading.offsetTop >= top ? picked : shown.sections.at(-1)!.id;
    }
    current = id;
  }

  call<Guide[]>('help.documents').then((list) => {
    guides = list;
    const last = remembered();
    const first = list.find((g) => g.file === last)?.file ?? (last === SHORTCUTS ? SHORTCUTS : list[0]?.file);
    if (first) open(first);
  });

  // Buscador: un momento después de dejar de escribir.
  $effect(() => {
    const text = query.trim();
    if (!text) {
      hits = null;
      return;
    }
    const timer = setTimeout(async () => {
      try {
        hits = await call<Hit[]>('help.search', text);
      } catch (err) {
        toast((err as Error).message, 'danger');
      }
    }, 200);
    return () => clearTimeout(timer);
  });

  function openHit(hit: Hit) {
    query = '';
    open(hit.file, hit.section);
  }

  /** Enlaces e imágenes de la guía (ver el comentario del principio). */
  function onclick(ev: MouseEvent) {
    const target = ev.target as Element;
    const image = target.closest<HTMLImageElement>('img');
    if (image) {
      zoomed = { src: image.src, alt: image.alt };
      return;
    }
    const link = target.closest<HTMLAnchorElement>('a[href]');
    if (!link) return;
    ev.preventDefault();
    const href = link.getAttribute('href') ?? '';
    if (href.startsWith('#')) goTo(href.slice(1));
    else if (href.startsWith('ayuda:')) {
      const name = href.slice(6).toLowerCase();
      const guide = all.find((g) => g.file.toLowerCase().includes(name));
      if (guide) open(guide.file);
    } else call('app.open_url', link.href);
  }

  function onkeydown(ev: KeyboardEvent) {
    if (ev.key === 'Escape' && zoomed) {
      ev.stopPropagation();
      zoomed = null;
    }
  }
</script>

<svelte:window {onkeydown} />

{#snippet keys(combo: string[])}
  {#each combo as key, i (i)}
    {#if i > 0}<span class="muted">+</span>{/if}<kbd class="keycap">{key}</kbd>
  {/each}
{/snippet}

{#snippet shortcutTables()}
  {#each t.settings.shortcuts.groups as [group, rows] (group)}
    <h2>{group}</h2>
    <div class="help-keys">
      {#each rows as [desc, combos] (desc)}
        <div class="help-keys__row">
          <span>{desc}</span>
          <span class="help-keys__combos">
            {#each combos as combo, i (i)}
              {#if i > 0}<span class="muted">{T.shortcuts.or}</span>{/if}{@render keys(combo)}
            {/each}
          </span>
        </div>
      {/each}
    </div>
  {/each}
{/snippet}

<div class="tool-page tool-page--fill">
  <ToolHeader emoji={tool.emoji} color={tool.color} title={T.title} subtitle={T.subtitle} />
  <hr class="divider" />
  <div class="help">
    <nav class="card help__nav" class:is-open={navOpen} aria-label={T.guides}>
      <div class="help__search">
        <Icon name="search" />
        <input class="help__search-input" type="search" placeholder={T.search} aria-label={T.searchLabel}
               bind:value={query} />
        {#if query}
          <button class="btn btn--icon btn--sm btn--ghost" type="button" title={T.clearSearch} aria-label={T.clearSearch}
                  onclick={() => (query = '')}><Icon name="x" /></button>
        {/if}
      </div>
      <!-- Pantalla estrecha: la guía abierta; al pulsar, la lista. -->
      <button class="help__current" type="button" aria-expanded={navOpen} onclick={() => (navOpen = !navOpen)}>
        <span class="help__guide-icon" aria-hidden="true">{shown?.icon}</span>
        <span class="ellipsis grow">{shown?.title ?? T.loading}</span>
        <Icon name="chevron-down" />
      </button>

      {#if hits}
        <p class="caption help__count" aria-live="polite">{hits.length ? T.results(hits.length) : T.noResults(query.trim())}</p>
        <ul class="help__hits">
          {#each hits as hit (hit.file + hit.section)}
            <li>
              <button class="help__hit" type="button" onclick={() => openHit(hit)}>
                <span class="help__hit-title">{hit.title}</span>
                {#if hit.section}<span class="caption">{hit.guide}</span>{/if}
                <span class="help__hit-snippet">{hit.snippet}</span>
              </button>
            </li>
          {/each}
        </ul>
      {:else}
        <ol class="help__guides">
          {#if guides && !guides.length}<li class="muted">{T.empty}</li>{/if}
          {#each all as guide (guide.file)}
            <li>
              <button class="help__guide" class:is-active={active === guide.file} type="button"
                      aria-current={active === guide.file ? 'page' : undefined} onclick={() => open(guide.file)}>
                <span class="help__guide-icon" aria-hidden="true">{guide.icon}</span>
                <span class="ellipsis">{guide.title}</span>
              </button>
              {#if active === guide.file && shown?.sections.length}
                <ol class="help__toc" aria-label={T.onThisPage}>
                  {#each shown.sections as section (section.id)}
                    <li>
                      <button class="help__toc-item" class:is-current={current === section.id} type="button"
                              onclick={() => goTo(section.id)}>{section.title}</button>
                    </li>
                  {/each}
                </ol>
              {/if}
            </li>
          {/each}
        </ol>
      {/if}
    </nav>

    <main class="card help__main" bind:this={main} {onscroll}>
      {#if shown}
        <header class="help__header">
          <span class="help__header-icon" aria-hidden="true">{shown.icon}</span>
          <div>
            <h1 class="help__title">{shown.title}</h1>
            {#if shown.summary}<p class="help__summary">{shown.summary}</p>{/if}
          </div>
        </header>
        <!-- HTML generado por el backend sin HTML crudo (seguro) -->
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
        <article class="markdown help-article" {onclick}>
          {#if active === SHORTCUTS}{@render shortcutTables()}{:else}{@html shown.html}{/if}
        </article>
        <footer class="help__pager">
          {#if index > 0}
            <button class="help__pager-link" type="button" onclick={() => open(all[index - 1].file)}>
              <span class="caption"><Icon name="chevron-left" size={14} /> {T.previous}</span>
              <span>{all[index - 1].icon} {all[index - 1].title}</span>
            </button>
          {/if}
          {#if index >= 0 && index < all.length - 1}
            <button class="help__pager-link help__pager-link--next" type="button" onclick={() => open(all[index + 1].file)}>
              <span class="caption">{T.next} <Icon name="chevron-right" size={14} /></span>
              <span>{all[index + 1].icon} {all[index + 1].title}</span>
            </button>
          {/if}
        </footer>
      {:else}
        <p class="muted">{guides && !guides.length ? T.empty : T.loading}</p>
      {/if}
    </main>
  </div>
</div>

{#if zoomed}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="help-zoom" onclick={() => (zoomed = null)}>
    <img src={zoomed.src} alt={zoomed.alt} />
    <button class="btn btn--icon help-zoom__close" type="button" title={T.closeImage} aria-label={T.closeImage}
            onclick={() => (zoomed = null)}><Icon name="x" /></button>
  </div>
{/if}
