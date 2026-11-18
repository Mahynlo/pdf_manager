<!--
  «OCR en todo el documento» (BatchOCRDialog en Qt): elegir páginas y procesarlas con
  progreso. Resuelve el texto de todas las páginas, o null si se cancela.
  `onPage(índice, resultado)` avisa de cada página reconocida.
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { call } from '$lib/api.ts';
  import Dialog from '$lib/components/Dialog.svelte';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { OcrResult } from './types.ts';

  const T = t.viewer.ocr.batchDialog;

  let { docId, recognize, total, setBusy, onPage, done }: {
    docId: number;
    /** OCR de una página (recognize.ts). */
    recognize: (index: number) => Promise<OcrResult>;
    total: number;
    setBusy: (busy: boolean) => void;
    onPage: (index: number, result: OcrResult) => void;
    done: (text: string | null) => void;
  } = $props();
  let dialog: Dialog;
  let customInput: HTMLInputElement;
  let scope = $state('all');
  let custom = $state('');
  let status = $state(T.ready);
  let progress = $state(0);
  let running = $state(false);
  let stopped = false;
  let result: string | null = null;

  async function scopeChanged() {
    await tick();
    if (scope === 'custom') customInput.focus();
  }

  async function start() {
    if (running) return;
    let pages: number[];
    try {
      pages = await call<number[]>('ocr.batch_pages', docId, scope, custom);
    } catch (err) {
      toast((err as Error).message, 'warning');
      return;
    }
    running = true;
    setBusy(true);
    status = T.starting(pages.length);
    const parts: string[] = [];
    try {
      for (const [step, index] of pages.entries()) {
        if (stopped) return;
        status = T.processing(index + 1, total);
        const pageResult = await recognize(index);
        parts.push(`${T.pageHeader(index + 1)}\n${pageResult.text}`);
        onPage(index, pageResult);
        progress = ((step + 1) / pages.length) * 100;
      }
      status = T.done;
      result = parts.join('\n\n');
      dialog.close();
    } catch (err) {
      const message = (err as Error).message;
      status = T.error(message);
      toast(T.failed(message), 'danger');
    } finally {
      running = false;
      setBusy(false);
    }
  }
</script>

<Dialog bind:this={dialog} class="ocr-batch" onclose={() => { stopped = true; done(result); }}>
  <h2 class="heading ocr-heading">{T.title}</h2>
  <p class="muted">{T.intro}</p>
  <RadioGroup bind:value={scope} onchange={scopeChanged} options={[
    { value: 'all', label: T.all(total) },
    { value: 'even', label: T.even },
    { value: 'odd', label: T.odd },
    { value: 'custom', label: T.custom },
  ]} />
  <input bind:this={customInput} bind:value={custom} class="input" type="text" placeholder={T.customPlaceholder}
         disabled={scope !== 'custom'} aria-label={T.customLabel} />
  <p class="caption">{status}</p>
  <div class="progress"><span style:width="{progress}%"></span></div>
  <div class="dialog__actions">
    <button class="btn btn--success" type="button" disabled={running} onclick={start}><Icon name="play" />{T.start}</button>
    <button class="btn" type="button" onclick={() => dialog.close()}>{T.cancel}</button>
  </div>
</Dialog>
