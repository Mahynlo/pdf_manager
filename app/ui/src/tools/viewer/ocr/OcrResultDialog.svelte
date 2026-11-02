<!-- «Resultado del Reconocimiento de Texto (OCR)»: copiar o guardar como TXT. -->
<script>
  import { call } from '$lib/api.js';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { setStatus, toast } from '$lib/ui.js';

  let { docId, text: initial, done } = $props();
  let dialog;
  // svelte-ignore state_referenced_locally
  let text = $state(initial); // se puede retocar antes de copiar o guardar

  function copy() {
    navigator.clipboard.writeText(text)
      .then(() => setStatus('Texto copiado al portapapeles'))
      .catch((err) => toast(`No se pudo copiar: ${err.message}`, 'danger'));
  }

  async function save() {
    try {
      const path = await call('ocr.save_text', docId, text);
      if (path) setStatus(`Archivo guardado en: ${path}`);
    } catch (err) {
      toast(err.message, 'danger');
    }
  }
</script>

<Dialog bind:this={dialog} class="ocr-result" onclose={() => done()}>
  <h2 class="heading ocr-heading">Texto extraído del documento:</h2>
  <textarea class="input textarea ocr-result__text" bind:value={text} aria-label="Texto extraído del documento"></textarea>
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={copy}><Icon name="copy" />Copiar al Portapapeles</button>
    <button class="btn" type="button" onclick={save}><Icon name="save" />Guardar como TXT...</button>
    <span class="grow"></span>
    <button class="btn btn--primary" type="button" onclick={() => dialog.close()}>Cerrar</button>
  </div>
</Dialog>
