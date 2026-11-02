<!--
  Barra lateral izquierda: miniaturas de página bajo demanda (como thumbnails.py en Qt).
  Clic → ir a esa página; arrastrar → mover la página. La imagen lleva las anotaciones
  (EmbedPDF la dibuja con ellas) y se vuelve a pedir cuando cambian las de su página.
-->
<script>
  import { onDestroy } from 'svelte';
  import { thumb, ThumbLoader } from '$lib/thumbs.js';

  /**
   * `revision` cambia con cada operación sobre las páginas (las miniaturas se vuelven a pedir);
   * `versions[página]`, con cada cambio de las anotaciones de esa página (se vuelve a pedir esa);
   * `fetchThumbs(páginas)` → { página: url } y `release(url)` las obtienen y liberan (ver canvas.js);
   * `onSelect(i)`: ir a la página; `onMove(src, dst)`: mover `src` a la posición final `dst`.
   */
  let { docId, count, current, revision, versions, visible, fetchThumbs, release, onSelect, onMove } = $props();

  // svelte-ignore state_referenced_locally
  const loader = new ThumbLoader((_id, pages) => fetchThumbs(pages), { release }); // funciones fijas del visor
  const cards = $state([]); // bind:this de cada tarjeta (para llevar la actual a la vista)
  let dragging = $state(-1);
  let mark = $state(null); // { index, after }

  const VERSIONS = 100000; // variante de la miniatura: operación de páginas y cambios de su página
  $effect(() => {
    if (revision) loader.forget(docId);
  });

  // La página actual queda a la vista en la lista.
  $effect(() => {
    if (visible) cards[current]?.scrollIntoView({ block: 'nearest' });
  });

  onDestroy(() => loader.disconnect());

  /** Posición de inserción según la mitad de la tarjeta sobre la que está el puntero. */
  const isAfter = (ev) => {
    const box = ev.currentTarget.getBoundingClientRect();
    return ev.clientY > box.top + box.height / 2;
  };

  function dragstart(ev, index) {
    if (count < 2) {
      ev.preventDefault();
      return;
    }
    dragging = index;
    ev.dataTransfer.effectAllowed = 'move';
    ev.dataTransfer.setData('text/plain', String(index));
  }

  function dragover(ev, index) {
    if (dragging < 0) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';
    mark = { index, after: isAfter(ev) };
  }

  function drop(ev, index) {
    if (dragging < 0) return;
    ev.preventDefault();
    const row = index + (isAfter(ev) ? 1 : 0);
    const dst = row > dragging ? row - 1 : row; // la fila de origen deja un hueco
    if (dst !== dragging) onMove(dragging, dst);
  }

  function dragend() {
    dragging = -1;
    mark = null;
  }
</script>

<aside class="viewer-sidebar" hidden={!visible}>
  <div class="thumb-list" role="listbox" aria-label="Miniaturas de página" tabindex="-1"
       ondragleave={(ev) => !ev.currentTarget.contains(ev.relatedTarget) && (mark = null)}>
    {#each { length: count }, i (i)}
      <button bind:this={cards[i]} class="thumb-card" class:is-active={i === current} class:is-dragging={i === dragging}
              class:drop-before={mark?.index === i && !mark.after} class:drop-after={mark?.index === i && mark.after}
              type="button" role="option" aria-selected={i === current} title="Página {i + 1}" draggable="true"
              onclick={() => onSelect(i)} ondragstart={(ev) => dragstart(ev, i)} ondragover={(ev) => dragover(ev, i)}
              ondrop={(ev) => drop(ev, i)} ondragend={dragend}>
        <span class="thumb-card__frame">
          <span class="thumb-card__page">
            <img class="thumb-card__img" alt="" draggable="false" use:thumb={[loader, docId, i, revision * VERSIONS + (versions[i] ?? 0)]} />
          </span>
        </span>
        <span class="caption">Pág {i + 1}</span>
      </button>
    {/each}
  </div>
</aside>
