<!--
  Nueva firma (como el diálogo de firmas de EmbedPDF): dibujarla, escribirla con una letra
  manuscrita o subir una imagen, y las iniciales si se quieren. Los paneles de dibujar y
  escribir son los de EmbedPDF. Resuelve la firma y si se guarda en el equipo, o null.
-->
<script module lang="ts">
  import type { SignatureEntry } from '@embedpdf/plugin-signature';

  /** Lo que resuelve el diálogo: la firma (para addEntry) y si se guarda en este equipo. */
  export interface NewSignature {
    entry: Omit<SignatureEntry, 'id' | 'createdAt'>;
    keep: boolean;
  }
</script>

<script lang="ts">
  import { SignatureCreationType, type SignatureFieldDefinition } from '@embedpdf/plugin-signature';
  import { SignatureDrawPad, SignatureTypePad } from '@embedpdf/plugin-signature/svelte';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Dialog from '$lib/components/Dialog.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import { untrack, type Snippet } from 'svelte';
  import { rasterize } from './stamp-pdf.ts';

  type Field = SignatureFieldDefinition | null;
  type Pad = { clear(): void };

  const T = t.viewer.signatures.dialog;
  const IMAGES = 'image/png,image/jpeg,image/webp,image/svg+xml';
  const DRAW = 0;
  const TYPE = 1;
  const UPLOAD = 2;

  let { done }: { done: (signature: NewSignature | null) => void } = $props();
  let dialog: Dialog;
  let method = $state(DRAW);
  let ink = $state(T.inks[0][0]);
  let font = $state(T.fonts[0][1]);
  let keep = $state(true);
  // Firma e iniciales de cada forma de crearla: cambiar de pestaña no borra lo hecho.
  let fields = $state.raw<[Field, Field][]>([[null, null], [null, null], [null, null]]);
  let pads = $state<(Pad | undefined)[][]>([[], []]); // paneles de dibujar y escribir (para «Borrar»)
  let dragging = $state(-1);
  let result: NewSignature | null = null;

  /**
   * Los paneles de EmbedPDF avisan (`onResult`) desde sus efectos: sin `untrack`, leer `fields`
   * ahí los suscribiría a lo que se escribe y se volverían a ejecutar sin fin.
   */
  function set(kind: number, which: number, value: Field) {
    untrack(() => {
      fields = fields.map((pair, i) => (i === kind ? pair.map((old, j) => (j === which ? value : old)) : pair)) as [Field, Field][];
    });
  }

  function clear(which: number) {
    if (method === UPLOAD) set(UPLOAD, which, null);
    else pads[method][which]?.clear();
  }

  const dataUrl = (blob: Blob) => new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });

  /** Imagen de la firma: se pasa a PNG (PDFium no pinta las SVG; la vista previa queda guardada). */
  async function load(file: File | undefined, which: number) {
    if (!file) return;
    try {
      const canvas = await rasterize(file);
      const png = await canvas.convertToBlob({ type: 'image/png' });
      set(UPLOAD, which, {
        creationType: SignatureCreationType.Upload, imageMimeType: 'image/png',
        imageSize: { width: canvas.width, height: canvas.height },
        previewDataUrl: await dataUrl(png), imageData: await png.arrayBuffer(),
      });
    } catch {
      toast(T.imageError, 'danger');
    }
  }

  function drop(ev: DragEvent, which: number) {
    ev.preventDefault();
    dragging = -1;
    load(ev.dataTransfer?.files[0], which);
  }

  function create() {
    const [signature, initials] = fields[method];
    if (!signature) return toast(T.missing, 'warning');
    result = { entry: initials ? { signature, initials } : { signature }, keep };
    dialog.close();
  }
</script>

{#snippet options(withFont: boolean)}
  <div class="signature-options">
    {#if withFont}
      <label class="signature-options__item"><span class="caption">{T.font}</span>
        <select class="input" bind:value={font}>
          {#each T.fonts as [name, family] (name)}
            <option value={family} style:font-family={family}>{name}</option>
          {/each}
        </select>
      </label>
    {/if}
    <span class="caption">{T.color}</span>
    {#each T.inks as [color, name] (color)}
      <button class="tb-swatch" class:is-checked={ink === color} type="button" title={name} aria-label={name}
              aria-pressed={ink === color} style:--swatch={color} onclick={() => (ink = color)}></button>
    {/each}
  </div>
{/snippet}

{#snippet field(label: string, which: number, content: Snippet)}
  <div class="signature-field" class:signature-field--initials={which === 1}>
    <div class="signature-field__head">
      <span class="caption">{label}</span>
      <span class="grow"></span>
      <button class="btn btn--ghost btn--sm" type="button" onclick={() => clear(which)}><Icon name="eraser" />{T.clear}</button>
    </div>
    {@render content()}
  </div>
{/snippet}

{#snippet drawTab()}
  <div class="signature-tab">
    {@render options(false)}
    {#snippet signaturePad()}
      <div class="signature-pad">
        <SignatureDrawPad bind:this={pads[DRAW][0]} class="signature-pad__fill" strokeColor={ink}
                          onResult={(value) => set(DRAW, 0, value)} />
      </div>
    {/snippet}
    {#snippet initialsPad()}
      <div class="signature-pad signature-pad--initials">
        <SignatureDrawPad bind:this={pads[DRAW][1]} class="signature-pad__fill" strokeColor={ink}
                          onResult={(value) => set(DRAW, 1, value)} />
      </div>
    {/snippet}
    {@render field(T.signature, 0, signaturePad)}
    {@render field(T.initials, 1, initialsPad)}
    <p class="caption">{T.drawHint}</p>
  </div>
{/snippet}

{#snippet typeTab()}
  <div class="signature-tab">
    {@render options(true)}
    {#snippet signaturePad()}
      <div class="signature-pad">
        <SignatureTypePad bind:this={pads[TYPE][0]} class="signature-pad__fill" fontFamily={font} color={ink}
                          placeholder={T.typePlaceholder} onResult={(value) => set(TYPE, 0, value)} />
      </div>
    {/snippet}
    {#snippet initialsPad()}
      <div class="signature-pad signature-pad--initials">
        <SignatureTypePad bind:this={pads[TYPE][1]} class="signature-pad__fill" fontFamily={font} color={ink}
                          fontSize={36} placeholder={T.initialsPlaceholder} onResult={(value) => set(TYPE, 1, value)} />
      </div>
    {/snippet}
    {@render field(T.signature, 0, signaturePad)}
    {@render field(T.initials, 1, initialsPad)}
  </div>
{/snippet}

{#snippet dropZone(which: number, hint: string)}
  {@const value = fields[UPLOAD][which]}
  <label class="signature-pad signature-drop" class:signature-pad--initials={which === 1} class:is-dragging={dragging === which}
         ondragover={(ev) => { ev.preventDefault(); dragging = which; }} ondragleave={() => (dragging = -1)}
         ondrop={(ev) => drop(ev, which)}>
    {#if value}
      <img class="signature-drop__img" src={value.previewDataUrl} alt="" draggable="false" />
    {:else}
      <Icon name="image" size={22} /><span class="caption">{hint}</span>
    {/if}
    <input type="file" accept={IMAGES} hidden onchange={(ev) => {
      load(ev.currentTarget.files?.[0], which);
      ev.currentTarget.value = '';
    }} />
  </label>
{/snippet}

{#snippet uploadTab()}
  <div class="signature-tab">
    {#snippet signatureZone()}{@render dropZone(0, T.uploadHint)}{/snippet}
    {#snippet initialsZone()}{@render dropZone(1, T.uploadInitials)}{/snippet}
    {@render field(T.signature, 0, signatureZone)}
    {@render field(T.initials, 1, initialsZone)}
  </div>
{/snippet}

<Dialog bind:this={dialog} class="signature-dialog" onclose={() => done(result)}>
  <div class="dialog__head"><Icon name="signature" size={20} /><h2 class="heading">{T.title}</h2></div>
  <SubTabs bind:current={method} tabs={[
    { label: T.draw, icon: 'pencil', panel: drawTab },
    { label: T.type, icon: 'type', panel: typeTab },
    { label: T.upload, icon: 'image', panel: uploadTab },
  ]} />
  <Checkbox label={T.keep} title={T.keepHint} bind:checked={keep} />
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={() => dialog.close()}>{t.common.cancel}</button>
    <button class="btn btn--primary" type="button" onclick={create}><Icon name="signature" />{T.create}</button>
  </div>
</Dialog>
