<!-- «Resultado del Reconocimiento de Texto (OCR)»: copiar o guardar como TXT. -->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { setStatus, toast } from '$lib/ui.ts';
  import { t } from '$texts';

  const T = t.viewer.ocr.result;

  let { docId, text: initial, done }: { docId: number; text: string; done: () => void } = $props();
  let dialog: Dialog;
  // svelte-ignore state_referenced_locally
  let text = $state(initial); // se puede retocar antes de copiar o guardar

  function copy() {
    navigator.clipboard.writeText(text)
      .then(() => setStatus(T.copied))
      .catch((err: Error) => toast(t.viewer.ocr.copyError(err.message), 'danger'));
  }

  async function save() {
    try {
      const path = await call<string | null>('ocr.save_text', docId, text);
      if (path) setStatus(T.saved(path));
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }
</script>

<Dialog bind:this={dialog} class="ocr-result" onclose={() => done()}>
  <h2 class="heading ocr-heading">{T.title}</h2>
  <textarea class="input textarea ocr-result__text" bind:value={text} aria-label={T.title}></textarea>
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={copy}><Icon name="copy" />{T.copy}</button>
    <button class="btn" type="button" onclick={save}><Icon name="save" />{T.save}</button>
    <span class="grow"></span>
    <button class="btn btn--primary" type="button" onclick={() => dialog.close()}>{T.close}</button>
  </div>
</Dialog>
