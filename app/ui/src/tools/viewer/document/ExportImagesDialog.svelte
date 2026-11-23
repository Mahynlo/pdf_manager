<!--
  «Exportar páginas como imágenes»: formato, resolución y páginas, con progreso y «Cancelar».
  El motor dibuja cada página tal como se ve, con sus anotaciones (`render`), la ventana la codifica
  y Python la escribe en la carpeta elegida (viewer.pick_images_folder / save_page_image).
  Resuelve `{ count, folder }` o null si se cancela antes de empezar.
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { call, send } from '$lib/api.ts';
  import Dialog from '$lib/components/Dialog.svelte';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import Icon from '$lib/Icon.svelte';
  import type { PageImage } from '$lib/pdf-engine/index.ts';
  import { t } from '$texts';

  const T = t.images.export;
  const RESOLUTIONS = [96, 150, 300];
  const JPEG_QUALITY = 0.9;

  let { docId, total, current, render, done }: {
    docId: number;
    total: number;
    current: number; // página actual, desde 0
    /** La página `index` en RGB a `scale` píxeles por punto. */
    render: (index: number, scale: number) => Promise<PageImage>;
    done: (result: { count: number; folder: string } | null) => void;
  } = $props();
  let dialog: Dialog;
  let customInput: HTMLInputElement;
  let format = $state('png'); // 'png' | 'jpg'
  let resolution = $state('150');
  let scope = $state('all');
  let custom = $state('');
  let status = $state('');
  let error = $state('');
  let progress = $state(0);
  let running = $state(false);
  let stopped = false;
  let result: { count: number; folder: string } | null = null;
  let saved = { count: 0, folder: '' }; // lo guardado hasta ahora (si se cancela a medias)

  /** «1-3, 5» → [0, 1, 2, 4]; null si no se entiende o se sale del documento. */
  function parseRange(text: string): number[] | null {
    const found = new Set<number>();
    for (const part of text.split(/[,;]/).map((p) => p.trim()).filter(Boolean)) {
      const match = /^(\d+)\s*(?:-\s*(\d+))?$/.exec(part);
      if (!match) return null;
      const [from, to] = [Number(match[1]), Number(match[2] ?? match[1])];
      if (from < 1 || to > total || from > to) return null;
      for (let page = from; page <= to; page++) found.add(page - 1);
    }
    return found.size ? [...found].sort((a, b) => a - b) : null;
  }

  async function scopeChanged() {
    await tick();
    if (scope === 'custom') customInput.focus();
  }

  /** RGB → PNG o JPG. */
  async function encode({ width, height, data }: PageImage): Promise<ArrayBuffer> {
    const rgb = new Uint8Array(data);
    const rgba = new Uint8ClampedArray(width * height * 4);
    for (let i = 0, j = 0; i < rgb.length; i += 3, j += 4) {
      rgba[j] = rgb[i];
      rgba[j + 1] = rgb[i + 1];
      rgba[j + 2] = rgb[i + 2];
      rgba[j + 3] = 255;
    }
    const canvas = new OffscreenCanvas(width, height);
    canvas.getContext('2d')!.putImageData(new ImageData(rgba, width, height), 0, 0);
    const blob = await canvas.convertToBlob(format === 'png' ? { type: 'image/png' } : { type: 'image/jpeg', quality: JPEG_QUALITY });
    return blob.arrayBuffer();
  }

  async function start() {
    if (running) return;
    const pages = scope === 'all' ? Array.from({ length: total }, (_, i) => i) : scope === 'current' ? [current] : parseRange(custom);
    if (!pages) {
      error = T.badRange(total);
      return;
    }
    error = '';
    const target = await call<{ folder: string; stem: string } | null>('viewer.pick_images_folder', docId);
    if (!target) return;
    running = true;
    const scale = Number(resolution) / 72;
    const digits = String(total).length;
    let count = 0;
    saved = { count, folder: target.folder };
    try {
      for (const index of pages) {
        if (stopped) break;
        status = T.progress(index + 1, count + 1, pages.length);
        const image = await render(index, scale);
        const name = `${target.stem}_p${String(index + 1).padStart(digits, '0')}.${format}`;
        await call('viewer.save_page_image', target.folder, name, await send(await encode(image)));
        count++;
        saved.count = count;
        progress = (count / pages.length) * 100;
      }
      result = { count, folder: target.folder };
      dialog.close();
    } catch (err) {
      error = T.failed((err as Error).message);
      if (count) result = { count, folder: target.folder };
    } finally {
      running = false;
    }
  }
</script>

<Dialog bind:this={dialog} class="export-images" onclose={() => { stopped = true; done(result ?? (saved.count ? saved : null)); }}>
  <h2 class="heading">{T.title}</h2>
  <p class="muted">{T.intro}</p>
  <div class="export-images__grid">
    <span class="label">{T.format}</span>
    <RadioGroup bind:value={format} options={Object.entries(T.formats).map(([value, label]) => ({ value, label }))} />
    <span class="label">{T.resolution}</span>
    <select class="input select" bind:value={resolution} disabled={running}>
      {#each RESOLUTIONS as dpi (dpi)}<option value={String(dpi)}>{T.resolutions[dpi]}</option>{/each}
    </select>
    <span class="label">{T.pages}</span>
    <div class="export-images__pages">
      <RadioGroup bind:value={scope} onchange={scopeChanged} options={[
        { value: 'all', label: T.all(total) },
        { value: 'current', label: T.current(current + 1) },
        { value: 'custom', label: T.custom },
      ]} />
      <input bind:this={customInput} bind:value={custom} class="input" type="text" placeholder={T.customPlaceholder}
             disabled={scope !== 'custom'} aria-label={T.customLabel} />
    </div>
  </div>
  <p class="caption">{status}</p>
  <div class="progress"><span style:width="{progress}%"></span></div>
  {#if error}<p class="dialog__error">{error}</p>{/if}
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={() => dialog.close()}>{T.cancel}</button>
    <button class="btn btn--primary" type="button" disabled={running} onclick={start}><Icon name="download" />{T.start}</button>
  </div>
</Dialog>
