<!-- Progreso con «Cancelar» (progressDialog); `progress` lo actualiza quien lo abrió. -->
<script lang="ts">
  import type { Progress } from '../dialogs.svelte.ts';
  import Dialog from './Dialog.svelte';
  import { t } from '$texts';

  let { title, progress, done }: { title: string; progress: Progress; done: () => void } = $props();
  let dialog: Dialog;

  $effect(() => {
    if (progress.closed) dialog.close();
  });
</script>

<Dialog bind:this={dialog} class="progress-dialog" onclose={() => done()}>
  <h2 class="heading">{title}</h2>
  <p class="muted">{progress.message}</p>
  <div class="progress"><span style:width="{progress.total ? (progress.done / progress.total) * 100 : 0}%"></span></div>
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={() => dialog.close()}>{t.common.cancel}</button>
  </div>
</Dialog>
