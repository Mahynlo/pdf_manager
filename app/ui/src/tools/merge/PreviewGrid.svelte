<!--
  «Vista previa del resultado»: las páginas en el orden final. Se reordenan
  arrastrando (pueden intercalarse documentos) y doble clic las amplía.
-->
<script>
  import { thumb } from '$lib/thumbs.js';

  /** `onReorder([[id, página], …])`; `onOpen(índice)`. */
  let { merge, thumbs, onReorder, onOpen } = $props();

  const byId = $derived(new Map(merge.entries.map((e) => [e.id, e])));
  const tiles = $derived(merge.preview.map(([id, page]) => ({ key: `${id}:${page}`, id, page, entry: byId.get(id) })));

  let dragKey = $state(null);
  let mark = $state(null); // { key, side: 'before' | 'after' }

  const sideOf = (ev) => {
    const box = ev.currentTarget.getBoundingClientRect();
    return ev.clientX < box.left + box.width / 2 ? 'before' : 'after';
  };

  function dragover(ev, key) {
    if (!dragKey) return;
    ev.preventDefault();
    mark = key === dragKey ? null : { key, side: sideOf(ev) };
  }

  function drop(ev, key) {
    if (!dragKey || key === dragKey) return;
    ev.preventDefault();
    const keys = tiles.map((t) => t.key).filter((k) => k !== dragKey);
    keys.splice(keys.indexOf(key) + (sideOf(ev) === 'after' ? 1 : 0), 0, dragKey);
    onReorder(keys.map((k) => k.split(':').map(Number)));
  }

  function dragend() {
    dragKey = null;
    mark = null;
  }
</script>

<div class="preview-grid">
  {#each tiles as tile, index (tile.key)}
    <div class="tile" class:is-dragging={dragKey === tile.key}
         class:drop-before={mark?.key === tile.key && mark.side === 'before'}
         class:drop-after={mark?.key === tile.key && mark.side === 'after'}
         style:--c={tile.entry.accent} title="{tile.entry.name} — página {tile.page + 1}"
         draggable="true" role="listitem"
         ondragstart={(ev) => { dragKey = tile.key; ev.dataTransfer.effectAllowed = 'move'; }}
         ondragover={(ev) => dragover(ev, tile.key)} ondrop={(ev) => drop(ev, tile.key)} ondragend={dragend}
         ondblclick={() => onOpen(index)}>
      <img alt="Página {tile.page + 1}" draggable="false" use:thumb={[thumbs, tile.id, tile.page, tile.entry.rotation]} />
      <span class="tile__label"><b>Pág. {tile.page + 1}</b><span class="ellipsis">{tile.entry.name}</span></span>
    </div>
  {/each}
</div>
