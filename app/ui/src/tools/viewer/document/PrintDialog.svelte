<!--
  Diálogo «Imprimir» del visor (print_dialog.py en Qt): páginas, subconjunto, orden
  inverso, orientación, color y escala, con vista previa. Al aceptar prepara las
  imágenes con progreso y abre el diálogo de impresión del sistema (ver print.js).
  `sizes`: tamaño de cada página tal como se ve (para la orientación y el tamaño real);
  `render(páginas, dpi, gris)`: sus imágenes (las dibuja PDFium: canvas.pageImages).
-->
<script>
  import { tick } from 'svelte';
  import { call } from '$lib/api.js';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Dialog from '$lib/components/Dialog.svelte';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import Icon from '$lib/Icon.svelte';
  import { progressDialog, toast } from '$lib/ui.js';
  import { printSheets } from './print.js';

  const BATCH = 4; // páginas por tanda al preparar la impresión (entre tandas se puede cancelar)
  const RANGE_DELAY = 250; // ms: espera a que se termine de escribir el rango
  const PRINT_DPI = 150; // resolución de las páginas que se imprimen
  const PREVIEW_DPI = 60;

  let { docId, current, sizes, render, done } = $props();
  let dialog;
  let customInput;
  const total = $derived(sizes.length);

  let scope = $state('all');
  let custom = $state('');
  let subset = $state('all');
  let reverse = $state(false);
  let orientation = $state('auto');
  let color = $state('color');
  let scale = $state('fit');
  let pages = $state.raw([]);
  let index = $state(0); // posición en `pages` de la página que se previsualiza
  let pageText = $state('');
  let previewUrl = $state(null);
  const previews = new Map(); // página -> url de la vista previa
  let run = 0;
  let rangeTimer = 0;

  const page = $derived(pages[index]);
  const landscape = $derived(page !== undefined && sheetOrientation(page) === 'landscape');

  function sheetOrientation(p) {
    if (orientation !== 'auto') return orientation;
    const [w, ht] = sizes[p];
    return w > ht ? 'landscape' : 'portrait';
  }

  async function recompute() {
    const mine = ++run;
    try {
      const result = await call('viewer.print_selection', docId, scope, custom, current, subset, reverse);
      if (mine !== run) return;
      pages = result;
      index = 0;
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  async function scopeChanged() {
    recompute();
    await tick();
    if (scope === 'custom') customInput.focus();
  }

  function customChanged() {
    clearTimeout(rangeTimer);
    rangeTimer = setTimeout(recompute, RANGE_DELAY);
  }

  function go(i) {
    if (pages.length) index = Math.max(0, Math.min(pages.length - 1, i));
  }

  // Vista previa de la página elegida (se guarda para no volver a pedirla).
  $effect(() => {
    const p = page;
    pageText = p === undefined ? '' : String(index + 1);
    previewUrl = previews.get(p) ?? null;
    if (p === undefined || previews.has(p)) return;
    render([p], PREVIEW_DPI)
      .then(({ [p]: url }) => {
        if (!url) return;
        previews.set(p, url);
        if (pages[index] === p) previewUrl = url;
      })
      .catch((err) => toast(err.message, 'danger'));
  });

  async function print() {
    if (!pages.length) {
      toast('No hay ninguna página seleccionada para imprimir.', 'warning');
      return;
    }
    const selected = [...pages];
    const gray = color === 'gray';
    const options = { scale, orientation: (p) => sheetOrientation(p) };
    dialog.close();
    const progress = progressDialog('Imprimiendo', 'Preparando páginas para imprimir...');
    const images = [];
    try {
      for (let i = 0; i < selected.length && !progress.cancelled; i += BATCH) {
        progress.update(i, selected.length, `Preparando páginas para imprimir... (${Math.min(i + BATCH, selected.length)} de ${selected.length})`);
        const batch = selected.slice(i, i + BATCH);
        const urls = await render([...new Set(batch)], PRINT_DPI, gray);
        images.push(...batch.map((p) => urls[p]));
      }
    } catch (err) {
      toast(err.message, 'danger');
      return;
    } finally {
      const cancelled = progress.cancelled;
      progress.close();
      if (cancelled) release(images);
    }
    if (images.length === selected.length && images.every(Boolean)) printSheets(selected, images, sizes, options);
  }

  function release(urls) {
    for (const url of new Set(urls)) if (url) URL.revokeObjectURL(url);
    urls.length = 0;
  }

  recompute();
</script>

{#snippet nav(icon, title, onclick, disabled)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {disabled} {onclick}><Icon name={icon} /></button>
{/snippet}

<Dialog bind:this={dialog} class="print-dialog" onclose={() => {
  release([...previews.values()]);
  done();
}}>
  <div class="print-dialog__layout">
    <div class="print-dialog__options">
      <div class="dialog__head"><span class="print-dialog__icon"><Icon name="printer" size={22} /></span><h2 class="title">Imprimir</h2></div>
      <p class="caption print-dialog__note">
        <Icon name="info" size={14} />La impresora, las copias y la doble cara se eligen en el siguiente paso, en el diálogo de impresión del sistema.
      </p>
      <h3 class="heading">Páginas a Imprimir</h3>
      <RadioGroup bind:value={scope} onchange={scopeChanged} options={[
        { value: 'all', label: `Todas las páginas (1 - ${total})` },
        { value: 'current', label: `Página actual (${current + 1})` },
        { value: 'custom', label: 'Rango personalizado:' },
      ]} />
      <input bind:this={customInput} bind:value={custom} class="input" type="text" placeholder="Ej: 1-3, 5, 8"
             disabled={scope !== 'custom'} aria-label="Rango personalizado" oninput={customChanged} />
      <label class="field">
        <span class="caption">Subconjunto:</span>
        <select class="input select" bind:value={subset} onchange={recompute}>
          <option value="all">Todas las páginas</option>
          <option value="odd">Solo páginas impares</option>
          <option value="even">Solo páginas pares</option>
        </select>
      </label>
      <Checkbox label="Imprimir en orden inverso" bind:checked={reverse} onchange={recompute} />
      <div class="print-dialog__pair">
        <label class="field">
          <span class="caption">Orientación:</span>
          <select class="input select" bind:value={orientation}>
            <option value="auto">Automática</option>
            <option value="portrait">Vertical (Retrato)</option>
            <option value="landscape">Horizontal (Paisaje)</option>
          </select>
        </label>
        <label class="field">
          <span class="caption">Color:</span>
          <select class="input select" bind:value={color}>
            <option value="color">Color</option>
            <option value="gray">Escala de grises (B/N)</option>
          </select>
        </label>
      </div>
      <label class="field">
        <span class="caption">Escala:</span>
        <select class="input select" bind:value={scale}>
          <option value="fit">Ajustar a la página (Recomendado)</option>
          <option value="real">Tamaño real (100%)</option>
          <option value="fill">Rellenar página</option>
        </select>
      </label>
      <span class="grow"></span>
      <p class="caption print-dialog__summary">Total: {pages.length} página(s)</p>
      <div class="dialog__actions">
        <button class="btn" type="button" onclick={() => dialog.close()}>Cancelar</button>
        <button class="btn btn--primary" type="button" disabled={!pages.length} onclick={print}><Icon name="printer" />Imprimir</button>
      </div>
    </div>
    <div class="print-dialog__preview">
      <div class="print-dialog__preview-head">
        <h3 class="heading">Vista Previa</h3>
        <span class="grow"></span>
        <span class="print-dialog__indicator">
          {page === undefined ? 'Sin páginas seleccionadas' : `Página ${index + 1} de ${pages.length} (Doc: pág. ${page + 1})`}
        </span>
      </div>
      <div class="print-paper" class:is-landscape={landscape} data-scale={scale}>
        <div class="print-sheet-preview">
          {#if page === undefined}
            <p class="muted">Sin vista previa disponible</p>
          {:else if previewUrl}
            <img alt="Página {page + 1}" src={previewUrl} style:filter={color === 'gray' ? 'grayscale(1)' : ''} />
          {/if}
        </div>
      </div>
      <div class="print-dialog__nav">
        {@render nav('chevrons-left', 'Primera página a imprimir', () => go(0), !pages.length || index <= 0)}
        {@render nav('chevron-left', 'Página anterior', () => go(index - 1), !pages.length || index <= 0)}
        <input bind:value={pageText} class="input tb-page" type="text" inputmode="numeric" aria-label="Página de la vista previa"
               disabled={!pages.length} onkeydown={(ev) => { if (ev.key === 'Enter') { const n = parseInt(pageText, 10); if (Number.isFinite(n)) go(n - 1); } }} />
        <span class="muted">/ {pages.length}</span>
        {@render nav('chevron-right', 'Página siguiente', () => go(index + 1), !pages.length || index >= pages.length - 1)}
        {@render nav('chevrons-right', 'Última página a imprimir', () => go(pages.length - 1), !pages.length || index >= pages.length - 1)}
      </div>
    </div>
  </div>
</Dialog>
