<!--
  «Imágenes a PDF»: cómo encajan las imágenes en la hoja (tamaño, orientación, margen, encajar o
  rellenar) con la vista previa de todas las páginas tal como quedarán, y cada página con sus ajustes
  propios: giro y orientación (automática para todas, y a mano en las que haga falta). Crea el PDF
  con images.ts.
  `mode`: «create» (documento nuevo), «insert» (páginas en un documento abierto, detrás de `after`)
  o «adjust» (rehacer la página de una imagen: solo esa, con su giro y opciones en `page`).
  Resuelve `{ pages, pdf }` o null si se cancela; las imágenes que se quitan se sueltan aquí.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { t } from '$texts';
  import {
    imagesPdf, layout, loadImages, releaseImages, rotatedSize,
    type ImagePage, type Orientation, type PageOptions, type Rotation, type SourceImage,
  } from './images.ts';
  import { pickImageFiles, rememberedOptions, rememberOptions } from './pick.ts';

  const T = t.images.dialog;
  const PREVIEW = 300; // lado mayor de la vista grande, en píxeles CSS
  const THUMB = 96; // y de cada página de la cuadrícula
  const CM = 2.54 / 72; // centímetros por punto

  let { images: initial, mode = 'create', after = 0, page, done }: {
    images: SourceImage[];
    mode?: 'create' | 'insert' | 'adjust';
    after?: number; // «insert»: la página detrás de la que van (desde 0)
    page?: ImagePage; // «adjust»: la página que se rehace
    done: (result: { pages: ImagePage[]; pdf: ArrayBuffer } | null) => void;
  } = $props();

  /** Una página: su imagen, su giro y su orientación (`global`: la de todas). */
  interface Item {
    id: number;
    image: SourceImage;
    rotation: Rotation;
    orientation: Orientation | 'global';
  }
  let ids = 0;
  const newItem = (image: SourceImage, rotation: Rotation = 0): Item => ({ id: ++ids, image, rotation, orientation: 'global' });
  // svelte-ignore state_referenced_locally
  let items = $state<Item[]>(initial.map((image) => newItem(image, page?.rotation ?? 0)));
  // svelte-ignore state_referenced_locally
  let options = $state<PageOptions>({ ...(page?.options ?? rememberedOptions()) });
  let selected = $state(0);
  let busy = $state('');
  let error = $state('');
  let dragging: number | null = null;
  let dialog: Dialog;
  let result: { pages: ImagePage[]; pdf: ArrayBuffer } | null = null;
  const bitmaps = new Map<SourceImage, Promise<HTMLImageElement>>(); // para dibujar las vistas previas

  const index = $derived(Math.max(0, Math.min(selected, items.length - 1)));
  const current = $derived(items[index] as Item | undefined);
  const title = $derived(mode === 'adjust' ? T.titleAdjust : mode === 'insert' ? T.titleInsert : T.titleCreate);
  const intro = $derived(mode === 'adjust' ? T.introAdjust : mode === 'insert' ? T.introInsert(after + 1) : T.introCreate);
  const action = $derived(mode === 'adjust' ? T.apply : mode === 'insert' ? T.insert(items.length) : T.create);
  const fixedShape = $derived(options.paper === 'image'); // la hoja es la imagen: ni orientación ni ajuste

  /** Las opciones con que queda la página `item`. */
  function pageOptions(item: Item, opts: PageOptions = options): PageOptions {
    return { ...opts, orientation: item.orientation === 'global' ? opts.orientation : item.orientation };
  }

  /** «A4 · horizontal · 29,7 × 21 cm» de la página `item`. */
  function describe(item: Item): string {
    const [width, height] = rotatedSize(item.image, item.rotation);
    const sheet = layout(width, height, pageOptions(item));
    const cm = (points: number) => (Math.round(points * CM * 10) / 10).toLocaleString('es');
    const shape = sheet.width > sheet.height ? T.landscape : T.portrait;
    return T.pageInfo(T.paperShort[options.paper], shape, cm(sheet.width), cm(sheet.height));
  }

  // ── Páginas ──────────────────────────────────────────────────────────
  async function add() {
    const files = await pickImageFiles();
    if (!files.length) return;
    const { images, failed } = await loadImages(files);
    error = failed.length ? T.unreadable(failed) : '';
    items = [...items, ...images.map((image) => newItem(image))];
    if (images.length) selected = items.length - images.length;
  }

  function rotate(at: number) {
    items[at].rotation = ((items[at].rotation + 90) % 360) as Rotation;
  }

  function move(from: number, to: number) {
    if (to < 0 || to >= items.length || from === to) return;
    const next = [...items];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    items = next;
    selected = to;
  }

  function remove(at: number) {
    const [item] = items.splice(at, 1);
    if (!items.some((other) => other.image === item.image)) release([item.image]);
    selected = Math.max(0, Math.min(selected, items.length - 1));
  }

  function release(images: SourceImage[]) {
    for (const image of images) bitmaps.delete(image);
    releaseImages(images);
  }

  function dropOn(at: number) {
    if (dragging !== null) move(dragging, at);
    dragging = null;
  }

  /** Las flechas recorren las páginas; Supr quita la elegida. */
  function keydown(ev: KeyboardEvent) {
    if (mode === 'adjust' || !items.length || (ev.target as HTMLElement).closest('select, input')) return;
    const step = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[ev.key];
    if (step) {
      ev.preventDefault();
      selected = Math.max(0, Math.min(items.length - 1, index + step));
    } else if (ev.key === 'Delete') {
      ev.preventDefault();
      remove(index);
    }
  }

  // ── Vistas previas ───────────────────────────────────────────────────
  function element(image: SourceImage): Promise<HTMLImageElement> {
    let found = bitmaps.get(image);
    if (!found) {
      const picture = new Image();
      picture.src = image.url;
      found = picture.decode().then(() => picture);
      bitmaps.set(image, found);
    }
    return found;
  }

  interface Sheet {
    image: SourceImage;
    rotation: Rotation;
    options: PageOptions;
    size: number; // lado mayor en píxeles CSS
  }

  /** Dibuja en `canvas` la hoja tal como quedará en el PDF. */
  async function drawSheet(canvas: HTMLCanvasElement, { image, rotation, options: opts, size }: Sheet) {
    const context = canvas.getContext('2d');
    if (!context) return;
    const ratio = window.devicePixelRatio || 1;
    const [width, height] = rotatedSize(image, rotation);
    const sheet = layout(width, height, opts);
    const scale = size / Math.max(sheet.width, sheet.height);
    canvas.style.width = `${sheet.width * scale}px`;
    canvas.style.height = `${sheet.height * scale}px`;
    canvas.width = Math.round(sheet.width * scale * ratio);
    canvas.height = Math.round(sheet.height * scale * ratio);
    const picture = await element(image).catch(() => null);
    context.setTransform(scale * ratio, 0, 0, scale * ratio, 0, 0);
    context.fillStyle = '#fff';
    context.fillRect(0, 0, sheet.width, sheet.height);
    if (!picture) return;
    // El PDF cuenta y desde abajo; el lienzo, desde arriba.
    const { clip, image: box } = sheet;
    context.save();
    context.beginPath();
    context.rect(clip.x, sheet.height - clip.y - clip.height, clip.width, clip.height);
    context.clip();
    context.translate(box.x + box.width / 2, sheet.height - box.y - box.height / 2);
    context.rotate((rotation * Math.PI) / 180);
    const [w, h] = rotation % 180 ? [box.height, box.width] : [box.width, box.height];
    context.drawImage(picture, -w / 2, -h / 2, w, h);
    context.restore();
    if (opts.margin !== 'none' && size >= PREVIEW) {
      // El margen, marcado con discreción en la vista grande.
      context.setLineDash([4 / scale, 4 / scale]);
      context.lineWidth = 1 / scale;
      context.strokeStyle = 'rgba(26, 115, 232, 0.45)';
      context.strokeRect(clip.x, sheet.height - clip.y - clip.height, clip.width, clip.height);
    }
  }

  /** `use:sheet={…}`: el lienzo dibuja esa hoja y la vuelve a dibujar cuando cambia. */
  function sheet(canvas: HTMLCanvasElement, value: Sheet) {
    void drawSheet(canvas, value);
    return { update: (next: Sheet) => void drawSheet(canvas, next) };
  }

  // ── Crear ────────────────────────────────────────────────────────────
  async function create() {
    if (!items.length || busy) return;
    const pages = items.map((item) => ({ image: item.image, rotation: item.rotation, options: pageOptions(item) }));
    error = '';
    try {
      busy = T.preparing(1, pages.length);
      const pdf = await imagesPdf(pages, (at) => (busy = T.preparing(at + 1, pages.length)));
      if (mode !== 'adjust') rememberOptions(options);
      result = { pages, pdf };
      dialog.close();
    } catch (err) {
      error = T.failed((err as Error).message);
    } finally {
      busy = '';
    }
  }

  function closed() {
    const kept = new Set(result?.pages.map((p) => p.image) ?? []);
    // Al cancelar se sueltan las imágenes que trajo este diálogo, salvo la de «Ajustar», que es de su página.
    release(items.map((item) => item.image).filter((image) => !kept.has(image) && image !== page?.image));
    done(result);
  }

  onMount(() => () => bitmaps.clear());
</script>

<Dialog bind:this={dialog} class="images-dialog" onclose={closed} onkeydown={keydown}>
  <h2 class="heading">{title}</h2>
  <p class="muted">{intro}</p>

  <div class="images-dialog__options">
    <label class="images-dialog__field">
      <span class="label">{T.paper}</span>
      <select class="input select" bind:value={options.paper}>
        {#each Object.entries(T.papers) as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
    </label>
    <label class="images-dialog__field">
      <span class="label">{mode === 'adjust' ? T.orientation : T.orientationAll}</span>
      <select class="input select" bind:value={options.orientation} disabled={fixedShape}>
        {#each Object.entries(T.orientations) as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
    </label>
    <label class="images-dialog__field">
      <span class="label">{T.margin}</span>
      <select class="input select" bind:value={options.margin}>
        {#each Object.entries(T.margins) as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
    </label>
    <label class="images-dialog__field">
      <span class="label">{T.fit}</span>
      <select class="input select" bind:value={options.fit} disabled={fixedShape}>
        {#each Object.entries(T.fits) as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
    </label>
  </div>

  <div class="images-dialog__main">
    {#if mode !== 'adjust'}
      <div class="images-dialog__side">
        <div class="images-dialog__side-head">
          <span class="label">{T.pages(items.length)}</span>
          <button class="btn btn--sm" type="button" onclick={add} disabled={!!busy}><Icon name="plus" size={14} />{T.add}</button>
        </div>
        <ul class="images-grid" aria-label={T.list}>
          {#each items as item, at (item.id)}
            <li class="images-grid__item" class:is-active={at === index} draggable="true"
                ondragstart={() => (dragging = at)} ondragover={(ev) => ev.preventDefault()} ondrop={() => dropOn(at)}>
              <button class="images-grid__page" type="button" onclick={() => (selected = at)} title={item.image.name}>
                <span class="images-grid__sheet">
                  <canvas use:sheet={{ image: item.image, rotation: item.rotation, options: pageOptions(item), size: THUMB }}></canvas>
                  {#if item.orientation !== 'global' && !fixedShape}
                    <span class="images-grid__badge" title={T.manual}><Icon name="pencil" size={10} /></span>
                  {/if}
                </span>
                <span class="images-grid__name ellipsis">{at + 1}. {item.image.name}</span>
              </button>
            </li>
          {:else}
            <li class="images-grid__empty muted">{T.empty}</li>
          {/each}
        </ul>
      </div>
    {/if}

    <div class="images-dialog__page">
      <div class="images-dialog__preview" aria-label={T.preview}>
        {#if current}
          <canvas use:sheet={{ image: current.image, rotation: current.rotation, options: pageOptions(current), size: PREVIEW }}></canvas>
        {/if}
      </div>
      {#if current}
        <div class="images-dialog__nav">
          {#if mode !== 'adjust'}
            <button class="btn btn--icon btn--sm" type="button" title={T.previous} disabled={index === 0} onclick={() => (selected = index - 1)}><Icon name="chevron-left" size={14} /></button>
          {/if}
          <span class="caption images-dialog__info">
            {#if mode !== 'adjust'}<strong>{T.pageNumber(index + 1, items.length)}</strong>{' · '}{/if}{describe(current)}
          </span>
          {#if mode !== 'adjust'}
            <button class="btn btn--icon btn--sm" type="button" title={T.next} disabled={index === items.length - 1} onclick={() => (selected = index + 1)}><Icon name="chevron-right" size={14} /></button>
          {/if}
        </div>
        <div class="images-dialog__page-tools">
          {#if mode !== 'adjust' && !fixedShape}
            <div class="segmented" role="radiogroup" aria-label={T.pageOrientation}>
              {#each Object.entries(T.pageOrientations) as [value, label] (value)}
                <button type="button" role="radio" class="segmented__item" class:is-checked={current.orientation === value}
                        aria-checked={current.orientation === value}
                        onclick={() => (items[index].orientation = value as Item['orientation'])}>{label}</button>
              {/each}
            </div>
          {/if}
          <span class="images-dialog__buttons">
            <button class="btn btn--icon btn--sm" type="button" title={T.rotate} onclick={() => rotate(index)}><Icon name="rotate-cw" size={14} /></button>
            {#if mode !== 'adjust'}
              <button class="btn btn--icon btn--sm" type="button" title={T.moveUp} disabled={index === 0} onclick={() => move(index, index - 1)}><Icon name="arrow-up" size={14} /></button>
              <button class="btn btn--icon btn--sm" type="button" title={T.moveDown} disabled={index === items.length - 1} onclick={() => move(index, index + 1)}><Icon name="arrow-down" size={14} /></button>
              <button class="btn btn--icon btn--sm is-danger" type="button" title={T.remove} onclick={() => remove(index)}><Icon name="trash" size={14} /></button>
            {/if}
          </span>
        </div>
      {/if}
    </div>
  </div>

  {#if busy}<p class="caption">{busy}</p>{/if}
  {#if error}<p class="dialog__error">{error}</p>{/if}
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={() => dialog.close()}>{T.cancel}</button>
    <button class="btn btn--primary" type="button" disabled={!items.length || !!busy} onclick={create}>
      <Icon name={mode === 'create' ? 'file-plus' : 'image'} />{action}
    </button>
  </div>
</Dialog>
