<!-- Propiedades del documento (viewer.properties): título y filas etiqueta/valor. -->
<script>
  import Dialog from '$lib/components/Dialog.svelte';

  let { title, rows, done } = $props();
  let dialog;
</script>

<Dialog bind:this={dialog} class="properties-dialog" onclose={() => done()}>
  <h2 class="heading">{title}</h2>
  <dl class="properties">
    {#each rows as { label, value } (label)}
      <dt class="caption">{label}</dt>
      <dd>{value}</dd>
    {/each}
  </dl>
  <div class="dialog__actions"><button class="btn btn--primary" type="button" onclick={() => dialog.close()}>Aceptar</button></div>
</Dialog>
