<!-- Tarjeta de un PDF fuente: cabecera con acciones, selección rápida, rango y páginas como chips. -->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { thumb, type ThumbLoader } from '$lib/thumbs.ts';
  import { t } from '$texts';
  import type { EntryActions, MergeEntry } from './types.ts';

  const T = t.merge.entry;

  let { entry, first, last, thumbs, actions }: {
    entry: MergeEntry;
    first: boolean;
    last: boolean;
    thumbs: ThumbLoader;
    actions: EntryActions;
  } = $props();
  const id = $derived(entry.id);
</script>

<article class="card entry" style:--c={entry.accent}>
  <div class="entry__head">
    <span class="entry__dot"></span>
    <span class="entry__name ellipsis" title={entry.path}>{entry.name}</span>
    <span class="entry__count">{T.pages(entry.count, entry.total)}</span>
    <button class="btn btn--icon btn--sm" type="button" title={T.rotate} onclick={() => actions.rotate(id, 90)}>
      <Icon name="rotate-cw" />
    </button>
    <button class="btn btn--icon btn--sm" type="button" title={T.up} disabled={first} onclick={() => actions.move(id, -1)}>
      <Icon name="arrow-up" />
    </button>
    <button class="btn btn--icon btn--sm" type="button" title={T.down} disabled={last} onclick={() => actions.move(id, 1)}>
      <Icon name="arrow-down" />
    </button>
    <button class="btn btn--icon btn--sm is-danger" type="button" title={T.remove} onclick={() => actions.remove(id)}>
      <Icon name="trash" />
    </button>
  </div>
  <div class="entry__tools">
    <button class="btn btn--chip" type="button" onclick={() => actions.selectAll(id, true)}>{T.all}</button>
    <button class="btn btn--chip" type="button" onclick={() => actions.selectAll(id, false)}>{T.none}</button>
    <button class="btn btn--chip" type="button" onclick={() => actions.invert(id)}>{T.invert}</button>
    <input class="input input--sm entry__range" value={entry.range} placeholder={T.range(entry.total)}
           title={T.rangeTip}
           onkeydown={(ev) => ev.key === 'Enter' && actions.setRange(id, ev.currentTarget.value.trim())} />
  </div>
  <div class="chips">
    {#each entry.selected as selected, page (page)}
      <button class="chip" class:is-selected={selected} type="button" title={T.page(page + 1)} aria-pressed={selected}
              onclick={() => actions.toggle(id, page)}>
        <img alt="" draggable="false" use:thumb={[thumbs, id, page, entry.rotation]} />
        <span class="chip__num">{page + 1}</span>
      </button>
    {/each}
  </div>
</article>
