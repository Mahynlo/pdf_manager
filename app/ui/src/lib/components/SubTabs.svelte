<!--
  Pestañas internas de una herramienta (QTabWidget). Los paneles siguen montados al
  cambiar de pestaña, así no pierden lo escrito.

    {#snippet chat()}…{/snippet}
    <SubTabs tabs={[{ label: 'Chat', icon: 'message-circle', panel: chat }, …]} bind:current />
-->
<script>
  import Icon from '../Icon.svelte';

  let { tabs, current = $bindable(0) } = $props();
</script>

<div class="subtabs">
  <div class="subtabs__bar" role="tablist">
    {#each tabs as tab, i (i)}
      <button class="subtabs__tab" class:is-active={current === i} type="button" role="tab"
              aria-selected={current === i} onclick={() => (current = i)}>
        <Icon name={tab.icon} />{tab.label}
      </button>
    {/each}
  </div>
  {#each tabs as tab, i (i)}
    <div class="subtabs__panel" role="tabpanel" hidden={current !== i}>
      {@render tab.panel()}
    </div>
  {/each}
</div>
