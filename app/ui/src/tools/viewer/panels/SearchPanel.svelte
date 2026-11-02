<!--
  Pestaña «Buscar» del panel lateral (search_panel.py en Qt): buscar en todo el
  documento, distinguir mayúsculas, palabra completa, recorrer las coincidencias y lista
  de resultados con su fragmento de texto.

  Busca el complemento Search de EmbedPDF en el documento a la vista (paso 4 de
  docs/web/embedpdf.md), también en el texto de OCR, que va en él como texto invisible.
  Los resultados llegan página a página mientras busca. Todas las coincidencias se marcan
  en el lienzo y la actual, más fuerte.
-->
<script>
  import { tick } from 'svelte';
  import { MatchFlag } from '@embedpdf/models';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.js';

  /**
   * `canvas`: el lienzo (su documento en EmbedPDF y sus capas de marcas);
   * `redact(query)`: enviar el término buscado a la censura.
   */
  let { canvas, close, redact } = $props();

  let input;
  let list;
  let text = $state('');
  let caseSensitive = $state(false);
  let wholeWord = $state(false);
  let query = $state(''); // última consulta buscada
  let matches = $state.raw([]); // [{ page, rects, before, match, after, cutLeft, cutRight }]
  let current = $state(-1);
  let searching = $state(false);
  let run = 0; // descarta resultados de búsquedas anteriores
  const PAGE = 200; // filas de la lista que se pintan de cada vez (con miles, pintarlas todas tarda)
  let shown = $state(PAGE);
  let marks = []; // elementos marcados en el lienzo, por coincidencia

  const count = $derived.by(() => {
    if (searching) return matches.length ? `Buscando… ${matches.length}` : 'Buscando…';
    if (current >= 0) return `${current + 1} de ${matches.length}`;
    if (!query) return '0 coincidencias';
    return `${matches.length} coincidencia(s)`;
  });

  export function focus() {
    input.focus();
    input.select();
  }

  /** Busca `value` (p. ej. la selección del lienzo). */
  export function setQuery(value) {
    text = value.replace(/\s+/g, ' ').trim();
    search();
  }

  /** Tras cambiar el documento (páginas, OCR), vuelve a buscar sin moverse por él. */
  export function refresh() {
    if (query) search({ jump: false });
  }

  /** F3 / Shift+F3 y las flechas: la siguiente o la anterior coincidencia (en bucle). */
  export function step(delta) {
    if (!matches.length) return false;
    select((current + delta + matches.length) % matches.length);
    return true;
  }

  function plugin() {
    return canvas.registry.getPlugin('search');
  }

  /** Resultado de EmbedPDF → coincidencia del panel, en puntos de la página tal como se ve. */
  function toMatch({ pageIndex, rects, context }) {
    return {
      page: pageIndex,
      rects: rects.map((rect) => canvas.toView(pageIndex, rect)),
      before: context.before,
      match: context.match,
      after: context.after,
      cutLeft: context.truncatedLeft,
      cutRight: context.truncatedRight,
    };
  }

  function clearHits() {
    for (const mark of canvas.queryAll('.search-hit')) mark.remove();
    marks = [];
  }

  /** Marca en el lienzo las coincidencias `items`, que van a partir de la posición `from`. */
  function markHits(items, from) {
    items.forEach((item, i) => {
      marks[from + i] = item.rects.map((rect) => canvas.addMark(item.page, rect, 'search-hit'));
    });
  }

  async function search({ jump = true } = {}) {
    const mine = ++run;
    query = text.trim();
    clearHits();
    matches = [];
    current = -1;
    shown = PAGE;
    if (!query) {
      stop();
      return;
    }
    searching = true;
    try {
      await canvas.loading; // la versión del documento que se está cargando
      const documentId = canvas.shown;
      if (mine !== run || !documentId) return;
      const flags = [caseSensitive && MatchFlag.MatchCase, wholeWord && MatchFlag.MatchWholeWord].filter(Boolean);
      // Con la sesión parada, cambiar las opciones no lanza otra búsqueda por su cuenta.
      const scope = plugin().provides().forDocument(documentId);
      scope.stopSearch();
      scope.setFlags(flags);
      const task = plugin().searchAllPages(query, documentId, true);
      // Los avisos llegan página a página: se juntan y se pintan una vez por fotograma.
      let pending = [];
      let frame = 0;
      const flush = () => {
        frame = 0;
        if (mine !== run || !pending.length) return;
        markHits(pending, matches.length);
        matches = matches.concat(pending);
        pending = [];
        if (jump && current < 0) select(0);
      };
      task.onProgress(({ results }) => {
        if (mine !== run || !results?.length) return;
        pending.push(...results.map(toMatch));
        frame ||= requestAnimationFrame(flush);
      });
      const { results } = await task.toPromise();
      if (mine !== run) return;
      cancelAnimationFrame(frame);
      flush();
      if (results.length !== matches.length) {
        // Por si algún aviso de progreso se perdió: el resultado final manda.
        clearHits();
        matches = results.map(toMatch);
        markHits(matches, 0);
        if (current >= matches.length) current = -1;
      }
      if (jump && current < 0 && matches.length) select(0);
      else if (current >= 0) highlight(current);
    } catch (err) {
      if (mine === run) toast(`No se pudo buscar: ${err?.reason?.message ?? err?.message ?? err}`, 'danger');
    } finally {
      if (mine === run) searching = false;
    }
  }

  function stop() {
    const documentId = canvas.shown;
    if (documentId && canvas.registry) plugin().provides().forDocument(documentId).stopSearch();
  }

  function highlight(index) {
    for (const mark of canvas.queryAll('.search-hit.is-current')) mark.classList.remove('is-current');
    for (const mark of marks[index] ?? []) mark.classList.add('is-current');
  }

  async function select(index) {
    current = index;
    if (index >= shown) shown = Math.ceil((index + 1) / PAGE) * PAGE;
    const { page, rects } = matches[index];
    highlight(index);
    canvas.scrollToRect(page, rects[0]);
    await tick();
    list.children[index]?.scrollIntoView({ block: 'nearest' });
  }

  function reset() {
    run++;
    text = '';
    query = '';
    searching = false;
    clearHits();
    matches = [];
    current = -1;
    stop();
  }

  function onkeydown(ev) {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    // Enter con la misma consulta pasa a la siguiente coincidencia.
    if (text.trim() === query && matches.length) step(ev.shiftKey ? -1 : 1);
    else search();
  }

  function toggle(option) {
    if (option === 'case') caseSensitive = !caseSensitive;
    else wholeWord = !wholeWord;
    if (text.trim()) search();
  }
</script>

{#snippet button(icon, title, onclick)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {onclick}><Icon name={icon} /></button>
{/snippet}

<div class="search-panel">
  <div class="search-panel__head">
    <span class="search-panel__icon"><Icon name="search" size={20} /></span>
    <h2 class="heading">Buscar en el documento</h2>
    <span class="grow"></span>
    {@render button('x', 'Cerrar', close)}
  </div>
  <div class="search-panel__row">
    <input bind:this={input} bind:value={text} class="input" type="text" placeholder="Buscar texto..."
           aria-label="Buscar texto" {onkeydown} />
    <button class="btn btn--icon search-panel__case" class:is-checked={caseSensitive} type="button"
            title="Distinguir mayúsculas y minúsculas" aria-pressed={caseSensitive} onclick={() => toggle('case')}>Aa</button>
    <button class="btn btn--icon search-panel__case search-panel__word" class:is-checked={wholeWord} type="button"
            title="Solo palabras completas" aria-pressed={wholeWord} onclick={() => toggle('word')}>ab</button>
  </div>
  <div class="search-panel__row">
    {@render button('chevron-up', 'Coincidencia anterior (Shift+F3)', () => step(-1))}
    <span class="caption search-panel__count">{count}</span>
    {@render button('chevron-down', 'Siguiente coincidencia (F3)', () => step(1))}
    {@render button('x', 'Limpiar búsqueda', reset)}
    {@render button('scissors', 'Enviar término a Censura', () => query && redact(query))}
  </div>
  <div class="search-results" role="listbox" aria-label="Coincidencias" bind:this={list}>
    {#each matches.slice(0, shown) as match, i (i)}
      <button class="search-result" class:is-active={i === current} type="button" role="option" aria-selected={i === current}
              onclick={() => select(i)}>
        <span class="search-result__page">Pág {match.page + 1}</span>
        <span class="search-result__text">{match.cutLeft ? '…' : ''}{match.before ? `${match.before} ` : ''}<mark>{match.match}</mark>{match.after ? ` ${match.after}` : ''}{match.cutRight ? '…' : ''}</span>
      </button>
    {:else}
      {#if query && !searching}
        <p class="search-results__empty muted">Sin coincidencias encontradas</p>
      {/if}
    {/each}
    {#if matches.length > shown}
      <button class="btn btn--ghost btn--sm search-results__more" type="button" onclick={() => (shown += PAGE)}>
        Mostrar más ({matches.length - shown})
      </button>
    {/if}
  </div>
</div>
