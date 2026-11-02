<!--
  Pestaña «Índice»: árbol de marcadores del PDF. `toc` es la lista plana de PyMuPDF
  [{ level, title, page }]; `nodes` (uso interno) son los hijos ya anidados.
-->
<script>
  import Icon from '$lib/Icon.svelte';
  import Self from './TocTree.svelte';

  let { toc = [], nodes = null, onSelect } = $props();

  /** Anida la lista plana según `level`. */
  function tree(items) {
    const root = [];
    const stack = [{ level: 0, children: root }];
    for (const { level, title, page } of items) {
      while (stack.length > 1 && stack.at(-1).level >= level) stack.pop();
      const node = { title, page, children: [] };
      stack.at(-1).children.push(node);
      stack.push({ level, children: node.children });
    }
    return root;
  }

  const items = $derived(nodes ?? tree(toc));
  let collapsed = $state(new Set());

  function toggle(ev, node) {
    ev.stopPropagation();
    if (collapsed.has(node)) collapsed.delete(node);
    else collapsed.add(node);
    collapsed = new Set(collapsed);
  }
</script>

{#if !nodes && !items.length}
  <p class="toc-empty muted">(Sin marcadores)</p>
{:else}
  <ul class={nodes ? 'toc__children' : 'toc'} role={nodes ? 'group' : 'tree'}>
    {#each items as node, i (i)}
      <li class="toc__item" class:is-leaf={!node.children.length} class:is-collapsed={collapsed.has(node)} role="treeitem"
          aria-selected="false">
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="toc__row" title="{node.title} (pág. {node.page + 1})" onclick={() => onSelect(node.page)}>
          <button class="toc__toggle" type="button" tabindex="-1" aria-label="Expandir o contraer" onclick={(ev) => toggle(ev, node)}>
            <Icon name="chevron-down" size={14} />
          </button>
          <span class="ellipsis">{node.title}</span>
        </div>
        <Self nodes={node.children} {onSelect} />
      </li>
    {/each}
  </ul>
{/if}
