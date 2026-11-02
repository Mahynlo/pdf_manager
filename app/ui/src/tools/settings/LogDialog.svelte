<!-- Registro de diagnóstico, desplazado al final (lo más reciente). -->
<script lang="ts">
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { t } from '$texts';

  const T = t.settings.log;

  let { text, done }: { text: string; done: () => void } = $props();
  let dialog: Dialog;
  let pre: HTMLPreElement;

  $effect(() => {
    pre.scrollTop = pre.scrollHeight;
  });
</script>

<Dialog bind:this={dialog} class="log-dialog" onclose={() => done()}>
  <div class="dialog__head"><Icon name="file-text" size={20} /><h2 class="heading">{T.title}</h2></div>
  <pre class="log" bind:this={pre}>{text}</pre>
  <div class="dialog__actions"><button class="btn" type="button" onclick={() => dialog.close()}>{T.close}</button></div>
</Dialog>
