<!--
  «Imágenes a PDF»: ordenar, girar y quitar las imágenes, elegir cómo encajan en la hoja (tamaño,
  orientación, margen, encajar o rellenar) con vista previa, y crear el PDF (images.ts).
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
    type ImagePage, type PageOptions, type Rotation, type SourceImage,
  } from './images.ts';
  import { pickImageFiles, rememberedOptions, rememberOptions } from './pick.ts';

  const T = t.images.dialog;
  const PREVIEW = 260; // lado mayor de la vista previa, en píxeles CSS

  let { images: initial, mode = 'create', after = 0, page, done }: {
    images: SourceImage[];
    mode?: 'create' | 'insert' | 'adjust';
    after?: number; // «insert»: la página detrás de la que van (desde 0)
    page?: ImagePage; // «adjust»: la página que se rehace
    done: (result: { pages: ImagePage[]; pdf: ArrayBuffer } | null) => void;
  } = $props();

  interface Item {
    id: number;
    image: SourceImage;
    rotation: Rotation;
  }
  let ids = 0;
  // svelte-ignore state_referenced_locally
  let items = $state<Item[]>(initial.map((image) => ({ id: ++ids, image, rotation: page?.rotation ?? 0 })));
  // svelte-ignore state_referenced_locally
  let options = $state<PageOptions>({ ...(page?.options ?? rememberedOptions()) });
  let selected = $state(0);
  let busy = $state('');
  let error = $state('');
  let dragging: number | null = null;
  let dialog: Dialog;
  let preview: HTMLCanvasElement;
  let result: { pages: ImagePage[]; pdf: ArrayBuffer } | null = null;
  const bitmaps = new Map<SourceImage, HTMLImageElement>(); // para dibujar la vista previa

  const current = $derived(items[Math.min(selected, items.length - 1)]);
  const title = $derived(mode === 'adjust' ? T.titleAdjust : mode === 'insert' ? T.titleInsert : T.titleCreate);
  const intro = $derived(mode === 'adjust' ? T.introAdjust : mode === 'insert' ? T.introInsert(after + 1) : T.introCreate);
  const action = $derived(mode === 'adjust' ? T.apply : mode === 'insert' ? T.insert(items.length) : T.create);

  // ── Lista ────────────────────────────────────────────────────────────
  async function add() {
    const files = await pickImageFiles();
    if (!files.length) return;
    const { images, failed } = await loadImages(files);
    error = failed.length ? T.unreadable(failed) : '';
    items = [...items, ...images.map((image) => ({ id: ++ids, image, rotation: 0 as Rotation }))];
    if (images.length) selected = items.length - images.length;
  }

  function rotate(index: number) {
    items[index].rotation = ((items[index].rotation + 90) % 360) as Rotation;
    selected = index;
  }

  function move(from: number, to: number) {
    if (to < 0 || to >= items.length || from === to) return;
    const next = [...items];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    items = next;
    selected = to;
  }

  function remove(index: number) {
    const [item] = items.splice(index, 1);
    if (!items.some((other) => other.image === item.image)) release([item.image]);
    selected = Math.max(0, Math.min(selected, items.length - 1));
  }

  function release(images: SourceImage[]) {
    for (const image of images) bitmaps.delete(image);
    releaseImages(images);
  }

  function dropOn(index: number) {
    if (dragging !== null) move(dragging, index);
    dragging = null;
  }

  // ── Vista previa ─────────────────────────────────────────────────────
  async function element(image: SourceImage): Promise<HTMLImageElement> {
    let found = bitmaps.get(image);
    if (!found) {
      found = new Image();
      found.src = image.url;
      await found.decode();
      bitmaps.set(image, found);
    }
    return found;
  }

  async function draw(item: Item | undefined, opts: PageOptions) {
    const context = preview?.getContext('2d');
    if (!context) return;
    const ratio = window.devicePixelRatio || 1;
    if (!item) {
      preview.width = preview.height = 0;
      return;
    }
    const [width, height] = rotatedSize(item.image, item.rotation);
    const sheet = layout(width, height, opts);
    const scale = PREVIEW / Math.max(sheet.width, sheet.height);
    preview.style.width = `${sheet.width * scale}px`;
    preview.style.height = `${sheet.height * scale}px`;
    preview.width = Math.round(sheet.width * scale * ratio);
    preview.height = Math.round(sheet.height * scale * ratio);
    const picture = await element(item.image).catch(() => null);
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
    context.rotate((item.rotation * Math.PI) / 180);
    const [w, h] = item.rotation % 180 ? [box.height, box.width] : [box.width, box.height];
    context.drawImage(picture, -w / 2, -h / 2, w, h);
    context.restore();
  }

  $effect(() => {
    void draw(current ? { ...current } : undefined, { ...options });
  });

  // ── Crear ────────────────────────────────────────────────────────────
  async function create() {
    if (!items.length || busy) return;
    const pages = items.map(({ image, rotation }) => ({ image, rotation, options: { ...options } }));
    error = '';
    try {
      busy = T.preparing(1, pages.length);
      const pdf = await imagesPdf(pages, (index) => (busy = T.preparing(index + 1, pages.length)));
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

<Dialog bind:this={dialog} class="images-dialog" onclose={closed}>
  <h2 class="heading">{title}</h2>
  <p class="muted">{intro}</p>
  <div class="images-dialog__main">
    {#if mode !== 'adjust'}
      <div class="images-dialog__side">
        <span class="label">{T.list}</span>
        <ul class="images-list" aria-label={T.list}>
          {#each items as item, index (item.id)}
            <li class="images-list__item" class:is-active={index === selected} draggable="true"
                ondragstart={() => (dragging = index)} ondragover={(ev) => ev.preventDefault()} ondrop={() => dropOn(index)}>
              <button class="images-list__pick" type="button" onclick={() => (selected = index)} title={item.image.name}>
                <span class="images-list__thumb">
                  <img src={item.image.url} alt="" draggable="false" style:transform="rotate({item.rotation}deg)" />
                </span>
                <span class="images-list__name ellipsis">{index + 1}. {item.image.name}</span>
              </button>
              <span class="images-list__tools">
                <button class="btn btn--icon btn--sm" type="button" title={T.rotate} onclick={() => rotate(index)}><Icon name="rotate-cw" size={14} /></button>
                <button class="btn btn--icon btn--sm" type="button" title={T.moveUp} disabled={index === 0} onclick={() => move(index, index - 1)}><Icon name="arrow-up" size={14} /></button>
                <button class="btn btn--icon btn--sm" type="button" title={T.moveDown} disabled={index === items.length - 1} onclick={() => move(index, index + 1)}><Icon name="arrow-down" size={14} /></button>
                <button class="btn btn--icon btn--sm is-danger" type="button" title={T.remove} onclick={() => remove(index)}><Icon name="x" size={14} /></button>
              </span>
            </li>
          {:else}
            <li class="images-list__empty muted">{T.empty}</li>
          {/each}
        </ul>
        <button class="btn btn--sm" type="button" onclick={add} disabled={!!busy}><Icon name="plus" size={14} />{T.add}</button>
      </div>
    {/if}
    <div class="images-dialog__settings">
      <div class="images-dialog__preview" aria-label={T.preview}>
        <canvas bind:this={preview}></canvas>
        {#if mode === 'adjust' && current}
          <button class="btn btn--icon btn--sm images-dialog__turn" type="button" title={T.rotate} onclick={() => rotate(0)}><Icon name="rotate-cw" size={14} /></button>
        {/if}
      </div>
      <label class="images-dialog__field">
        <span class="label">{T.paper}</span>
        <select class="input select" bind:value={options.paper}>
          {#each Object.entries(T.papers) as [value, label] (value)}<option {value}>{label}</option>{/each}
        </select>
      </label>
      <label class="images-dialog__field">
        <span class="label">{T.orientation}</span>
        <select class="input select" bind:value={options.orientation} disabled={options.paper === 'image'}>
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
        <select class="input select" bind:value={options.fit} disabled={options.paper === 'image'}>
          {#each Object.entries(T.fits) as [value, label] (value)}<option {value}>{label}</option>{/each}
        </select>
      </label>
    </div>
  </div>
  <p class="caption">{busy || (mode === 'adjust' ? '' : T.pages(items.length))}</p>
  {#if error}<p class="dialog__error">{error}</p>{/if}
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={() => dialog.close()}>{T.cancel}</button>
    <button class="btn btn--primary" type="button" disabled={!items.length || !!busy} onclick={create}>
      <Icon name={mode === 'create' ? 'file-plus' : 'image'} />{action}
    </button>
  </div>
</Dialog>
