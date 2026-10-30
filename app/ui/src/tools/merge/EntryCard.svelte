<!-- Tarjeta de un PDF fuente: cabecera con acciones, selección rápida, rango y páginas como chips. -->
<script>
  import Icon from '$lib/Icon.svelte';
  import { thumb } from '$lib/thumbs.js';

  /** `actions`: { toggle, selectAll, invert, setRange, rotate, move, remove } (ver Merge.svelte). */
  let { entry, first, last, thumbs, actions } = $props();
  const id = $derived(entry.id);
</script>

<article class="card entry" style:--c={entry.accent}>
  <div class="entry__head">
    <span class="entry__dot"></span>
    <span class="entry__name ellipsis" title={entry.path}>{entry.name}</span>
    <span class="entry__count">{entry.count}/{entry.total} págs.</span>
    <button class="btn btn--icon btn--sm" type="button" title="Girar 90° a la derecha" onclick={() => actions.rotate(id, 90)}>
      <Icon name="rotate-cw" />
    </button>
    <button class="btn btn--icon btn--sm" type="button" title="Mover arriba" disabled={first} onclick={() => actions.move(id, -1)}>
      <Icon name="arrow-up" />
    </button>
    <button class="btn btn--icon btn--sm" type="button" title="Mover abajo" disabled={last} onclick={() => actions.move(id, 1)}>
      <Icon name="arrow-down" />
    </button>
    <button class="btn btn--icon btn--sm is-danger" type="button" title="Quitar documento" onclick={() => actions.remove(id)}>
      <Icon name="trash" />
    </button>
  </div>
  <div class="entry__tools">
    <button class="btn btn--chip" type="button" onclick={() => actions.selectAll(id, true)}>Todas</button>
    <button class="btn btn--chip" type="button" onclick={() => actions.selectAll(id, false)}>Ninguna</button>
    <button class="btn btn--chip" type="button" onclick={() => actions.invert(id)}>Invertir</button>
    <input class="input input--sm entry__range" value={entry.range} placeholder="Rango (1-{entry.total})"
           title="Páginas a incluir, p. ej. 1-3, 5. Enter para aplicar"
           onkeydown={(ev) => ev.key === 'Enter' && actions.setRange(id, ev.currentTarget.value.trim())} />
  </div>
  <div class="chips">
    {#each entry.selected as selected, page (page)}
      <button class="chip" class:is-selected={selected} type="button" title="Página {page + 1}" aria-pressed={selected}
              onclick={() => actions.toggle(id, page)}>
        <img alt="" draggable="false" use:thumb={[thumbs, id, page, entry.rotation]} />
        <span class="chip__num">{page + 1}</span>
      </button>
    {/each}
  </div>
</article>
