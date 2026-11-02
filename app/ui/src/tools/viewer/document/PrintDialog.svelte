<!--
  Diálogo «Imprimir» del visor (print_dialog.py en Qt): páginas, subconjunto, orden
  inverso, orientación, color y escala, con vista previa. Al aceptar prepara las
  imágenes con progreso y abre el diálogo de impresión del sistema (ver print.ts).
  `sizes`: tamaño de cada página tal como se ve (para la orientación y el tamaño real);
  `render(páginas, dpi, gris)`: sus imágenes (las dibuja PDFium: canvas.pageImages).
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { call } from '$lib/api.ts';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Dialog from '$lib/components/Dialog.svelte';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import Icon from '$lib/Icon.svelte';
  import { progressDialog, toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import { printSheets, type Orientation, type PrintScale } from './print.ts';

  const T = t.viewer.print;
  const BATCH = 4; // páginas por tanda al preparar la impresión (entre tandas se puede cancelar)
  const RANGE_DELAY = 250; // ms: espera a que se termine de escribir el rango
  const PRINT_DPI = 150; // resolución de las páginas que se imprimen
  const PREVIEW_DPI = 60;

  /** Imágenes de `pages` a `dpi`: { página: url blob }. */
  type Render = (pages: number[], dpi: number, gray?: boolean) => Promise<Record<number, string>>;

  let { docId, current, sizes, render, done }: {
    docId: number;
    current: number;
    sizes: [number, number][];
    render: Render;
    done: () => void;
  } = $props();
  let dialog: Dialog;
  let customInput: HTMLInputElement;
  const total = $derived(sizes.length);

  let scope = $state('all');
  let custom = $state('');
  let subset = $state('all');
  let reverse = $state(false);
  let orientation = $state<'auto' | Orientation>('auto');
  let color = $state('color');
  let scale = $state<PrintScale>('fit');
  let pages = $state.raw<number[]>([]);
  let index = $state(0); // posición en `pages` de la página que se previsualiza
  let pageText = $state('');
  let previewUrl = $state<string | null>(null);
  const previews = new Map<number, string>(); // página -> url de la vista previa
  let run = 0;
  let rangeTimer = 0;

  const page = $derived<number | undefined>(pages[index]);
  const landscape = $derived(page !== undefined && sheetOrientation(page) === 'landscape');

  function sheetOrientation(p: number): Orientation {
    if (orientation !== 'auto') return orientation;
    const [w, ht] = sizes[p];
    return w > ht ? 'landscape' : 'portrait';
  }

  async function recompute() {
    const mine = ++run;
    try {
      const result = await call<number[]>('viewer.print_selection', docId, scope, custom, current, subset, reverse);
      if (mine !== run) return;
      pages = result;
      index = 0;
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  async function scopeChanged() {
    recompute();
    await tick();
    if (scope === 'custom') customInput.focus();
  }

  function customChanged() {
    clearTimeout(rangeTimer);
    rangeTimer = window.setTimeout(recompute, RANGE_DELAY);
  }

  function go(i: number) {
    if (pages.length) index = Math.max(0, Math.min(pages.length - 1, i));
  }

  // Vista previa de la página elegida (se guarda para no volver a pedirla).
  $effect(() => {
    const p = page;
    pageText = p === undefined ? '' : String(index + 1);
    previewUrl = (p !== undefined && previews.get(p)) || null;
    if (p === undefined || previews.has(p)) return;
    render([p], PREVIEW_DPI)
      .then(({ [p]: url }) => {
        if (!url) return;
        previews.set(p, url);
        if (pages[index] === p) previewUrl = url;
      })
      .catch((err: Error) => toast(err.message, 'danger'));
  });

  async function print() {
    if (!pages.length) {
      toast(T.nothing, 'warning');
      return;
    }
    const selected = [...pages];
    const gray = color === 'gray';
    const options = { scale, orientation: (p: number) => sheetOrientation(p) };
    dialog.close();
    const progress = progressDialog(T.progressTitle, T.preparing);
    const images: string[] = [];
    try {
      for (let i = 0; i < selected.length && !progress.cancelled; i += BATCH) {
        progress.update(i, selected.length, T.preparingCount(Math.min(i + BATCH, selected.length), selected.length));
        const batch = selected.slice(i, i + BATCH);
        const urls = await render([...new Set(batch)], PRINT_DPI, gray);
        images.push(...batch.map((p) => urls[p]));
      }
    } catch (err) {
      toast((err as Error).message, 'danger');
      return;
    } finally {
      const cancelled = progress.cancelled;
      progress.close();
      if (cancelled) release(images);
    }
    if (images.length === selected.length && images.every(Boolean)) printSheets(selected, images, sizes, options);
  }

  function release(urls: string[]) {
    for (const url of new Set(urls)) if (url) URL.revokeObjectURL(url);
    urls.length = 0;
  }

  function pageKey(ev: KeyboardEvent) {
    if (ev.key !== 'Enter') return;
    const n = parseInt(pageText, 10);
    if (Number.isFinite(n)) go(n - 1);
  }

  recompute();
</script>

{#snippet nav(icon: string, title: string, onclick: () => void, disabled: boolean)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {disabled} {onclick}><Icon name={icon} /></button>
{/snippet}

<Dialog bind:this={dialog} class="print-dialog" onclose={() => {
  release([...previews.values()]);
  done();
}}>
  <div class="print-dialog__layout">
    <div class="print-dialog__options">
      <div class="dialog__head"><span class="print-dialog__icon"><Icon name="printer" size={22} /></span><h2 class="title">{T.title}</h2></div>
      <p class="caption print-dialog__note">
        <Icon name="info" size={14} />{T.note}
      </p>
      <h3 class="heading">{T.pages}</h3>
      <RadioGroup bind:value={scope} onchange={scopeChanged} options={[
        { value: 'all', label: T.all(total) },
        { value: 'current', label: T.current(current + 1) },
        { value: 'custom', label: T.custom },
      ]} />
      <input bind:this={customInput} bind:value={custom} class="input" type="text" placeholder={T.customPlaceholder}
             disabled={scope !== 'custom'} aria-label={T.customLabel} oninput={customChanged} />
      <label class="field">
        <span class="caption">{T.subset}</span>
        <select class="input select" bind:value={subset} onchange={recompute}>
          <option value="all">{T.subsetAll}</option>
          <option value="odd">{T.subsetOdd}</option>
          <option value="even">{T.subsetEven}</option>
        </select>
      </label>
      <Checkbox label={T.reverse} bind:checked={reverse} onchange={recompute} />
      <div class="print-dialog__pair">
        <label class="field">
          <span class="caption">{T.orientation}</span>
          <select class="input select" bind:value={orientation}>
            <option value="auto">{T.orientationAuto}</option>
            <option value="portrait">{T.portrait}</option>
            <option value="landscape">{T.landscape}</option>
          </select>
        </label>
        <label class="field">
          <span class="caption">{T.color}</span>
          <select class="input select" bind:value={color}>
            <option value="color">{T.colorColor}</option>
            <option value="gray">{T.colorGray}</option>
          </select>
        </label>
      </div>
      <label class="field">
        <span class="caption">{T.scale}</span>
        <select class="input select" bind:value={scale}>
          <option value="fit">{T.scaleFit}</option>
          <option value="real">{T.scaleReal}</option>
          <option value="fill">{T.scaleFill}</option>
        </select>
      </label>
      <span class="grow"></span>
      <p class="caption print-dialog__summary">{T.total(pages.length)}</p>
      <div class="dialog__actions">
        <button class="btn" type="button" onclick={() => dialog.close()}>{T.cancel}</button>
        <button class="btn btn--primary" type="button" disabled={!pages.length} onclick={print}><Icon name="printer" />{T.print}</button>
      </div>
    </div>
    <div class="print-dialog__preview">
      <div class="print-dialog__preview-head">
        <h3 class="heading">{T.preview}</h3>
        <span class="grow"></span>
        <span class="print-dialog__indicator">
          {page === undefined ? T.noPages : T.indicator(index + 1, pages.length, page + 1)}
        </span>
      </div>
      <div class="print-paper" class:is-landscape={landscape} data-scale={scale}>
        <div class="print-sheet-preview">
          {#if page === undefined}
            <p class="muted">{T.noPreview}</p>
          {:else if previewUrl}
            <img alt={T.pageAlt(page + 1)} src={previewUrl} style:filter={color === 'gray' ? 'grayscale(1)' : ''} />
          {/if}
        </div>
      </div>
      <div class="print-dialog__nav">
        {@render nav('chevrons-left', T.first, () => go(0), !pages.length || index <= 0)}
        {@render nav('chevron-left', T.prev, () => go(index - 1), !pages.length || index <= 0)}
        <input bind:value={pageText} class="input tb-page" type="text" inputmode="numeric" aria-label={T.pageLabel}
               disabled={!pages.length} onkeydown={pageKey} />
        <span class="muted">/ {pages.length}</span>
        {@render nav('chevron-right', T.next, () => go(index + 1), !pages.length || index >= pages.length - 1)}
        {@render nav('chevrons-right', T.last, () => go(pages.length - 1), !pages.length || index >= pages.length - 1)}
      </div>
    </div>
  </div>
</Dialog>
