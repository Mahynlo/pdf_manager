<!-- Registro de diagnóstico, desplazado al final (lo más reciente). -->
<script>
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';

  let { text, done } = $props();
  let dialog;
  let pre;

  $effect(() => {
    pre.scrollTop = pre.scrollHeight;
  });
</script>

<Dialog bind:this={dialog} class="log-dialog" onclose={() => done()}>
  <div class="dialog__head"><Icon name="file-text" size={20} /><h2 class="heading">Registro de Diagnóstico</h2></div>
  <pre class="log" bind:this={pre}>{text}</pre>
  <div class="dialog__actions"><button class="btn" type="button" onclick={() => dialog.close()}>Cerrar</button></div>
</Dialog>
