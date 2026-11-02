<!--
  «OCR en todo el documento» (BatchOCRDialog en Qt): elegir páginas y procesarlas con
  progreso. Resuelve el texto de todas las páginas, o null si se cancela.
  `onPage(índice, resultado)` avisa de cada página reconocida.
-->
<script>
  import { tick } from 'svelte';
  import { call } from '$lib/api.js';
  import Dialog from '$lib/components/Dialog.svelte';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.js';

  let { docId, total, setBusy, onPage, done } = $props();
  let dialog;
  let customInput;
  let scope = $state('all');
  let custom = $state('');
  let status = $state('Listo para iniciar.');
  let progress = $state(0);
  let running = $state(false);
  let stopped = false;
  let result = null;

  async function scopeChanged() {
    await tick();
    if (scope === 'custom') customInput.focus();
  }

  async function start() {
    if (running) return;
    let pages;
    try {
      pages = await call('ocr.batch_pages', docId, scope, custom);
    } catch (err) {
      toast(err.message, 'warning');
      return;
    }
    running = true;
    setBusy(true);
    status = `Iniciando procesamiento de ${pages.length} páginas...`;
    const parts = [];
    try {
      for (const [step, index] of pages.entries()) {
        if (stopped) return;
        status = `Procesando página ${index + 1} de ${total}...`;
        const pageResult = await call('ocr.page', docId, index);
        parts.push(`--- PÁGINA ${index + 1} ---\n${pageResult.text}`);
        onPage(index, pageResult);
        progress = ((step + 1) / pages.length) * 100;
      }
      status = '¡Completado con éxito!';
      result = parts.join('\n\n');
      dialog.close();
    } catch (err) {
      status = `Error: ${err.message}`;
      toast(`Ocurrió un fallo en el procesamiento: ${err.message}`, 'danger');
    } finally {
      running = false;
      setBusy(false);
    }
  }
</script>

<Dialog bind:this={dialog} class="ocr-batch" onclose={() => { stopped = true; done(result); }}>
  <h2 class="heading ocr-heading">OCR en todo el documento</h2>
  <p class="muted">Selecciona las páginas que deseas procesar con el motor neuronal OCR:</p>
  <RadioGroup bind:value={scope} onchange={scopeChanged} options={[
    { value: 'all', label: `Todo el documento (${total} páginas)` },
    { value: 'even', label: 'Solo páginas pares' },
    { value: 'odd', label: 'Solo páginas impares' },
    { value: 'custom', label: 'Rango personalizado:' },
  ]} />
  <input bind:this={customInput} bind:value={custom} class="input" type="text" placeholder="Ej: 1-5, 8, 11-13"
         disabled={scope !== 'custom'} aria-label="Rango personalizado" />
  <p class="caption">{status}</p>
  <div class="progress"><span style:width="{progress}%"></span></div>
  <div class="dialog__actions">
    <button class="btn btn--success" type="button" disabled={running} onclick={start}><Icon name="play" />Iniciar OCR</button>
    <button class="btn" type="button" onclick={() => dialog.close()}>Cancelar</button>
  </div>
</Dialog>
