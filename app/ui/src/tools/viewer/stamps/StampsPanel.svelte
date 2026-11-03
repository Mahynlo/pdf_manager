<!--
  Pestaña «Sellos» del panel lateral: sellos (estándar, de texto y propios) y firmas. Un clic
  en uno lo deja listo y el siguiente clic en la página lo coloca, con su vista previa; Esc
  cancela. Las bibliotecas son de toda la app (library.svelte.ts, signatures.svelte.ts).
-->
<script lang="ts">
  import type { SignatureEntry } from '@embedpdf/plugin-signature';
  import Icon from '$lib/Icon.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import { askText, confirmDialog, openModal, setStatus, toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { Annotations } from '../annotations/annotations.ts';
  import { TOOLS, type PageCanvas } from '../canvas/canvas.ts';
  import LegendsDialog from './LegendsDialog.svelte';
  import { CUSTOM, stampLibraries as library, type StampItem } from './library.svelte.ts';
  import SignatureDialog, { type NewSignature } from './SignatureDialog.svelte';
  import { signatures } from './signatures.svelte.ts';
  import type { TextStamp } from './stamp-pdf.ts';

  const T = t.viewer.stamps;
  const TS = t.viewer.signatures;
  const IMAGES = 'image/png,image/jpeg,image/webp,image/svg+xml';

  /**
   * `canvas`: el lienzo (documento a la vista); `annotations`: las del documento (para crear un
   * sello con las seleccionadas); `setTool(t)`: herramienta del lienzo; `active`: la pestaña
   * se ve (las bibliotecas se cargan la primera vez).
   */
  let { canvas, annotations, setTool, active, close }: {
    canvas: PageCanvas;
    annotations: Annotations;
    setTool: (tool: string) => void;
    active: boolean;
    close: () => void;
  } = $props();

  let tab = $state(0);
  let picker = $state<HTMLInputElement>();

  /** Abre la pestaña de sellos (0) o la de firmas (1). */
  export function show(index: number) {
    tab = index;
  }

  /** Gestor de leyendas: lo que elija para insertar se coloca como un sello de texto. */
  export async function manageLegends() {
    const text = await openModal<TextStamp>(LegendsDialog);
    library.refresh(); // pudo crear o borrar leyendas
    if (text) arm(() => library.placeText(canvas.shown!, text), T.placeError);
  }

  $effect(() => {
    if (!active) return;
    if (!library.loaded) library.refresh();
    signatures.ready();
  });

  /** Deja listo para colocar: la herramienta del lienzo pasa a «colocar» y EmbedPDF pone la suya. */
  async function arm(activate: () => Promise<void>, error: (message: string) => string) {
    if (!canvas.shown) return;
    setTool(TOOLS.PLACE);
    try {
      await activate();
    } catch (err) {
      setTool(TOOLS.SELECT);
      toast(error((err as Error).message ?? String(err)), 'danger');
    }
  }

  const place = (item: StampItem) => arm(() => library.place(canvas.shown!, item), T.placeError);

  async function remove(item: StampItem) {
    if (!(await confirmDialog(T.removeTitle, T.removeQuestion(item.name)))) return;
    try {
      await library.remove(item);
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  /** Crea un sello propio con `create(nombre)` tras pedir el nombre. */
  async function addCustom(suggested: string, create: (name: string) => Promise<void>) {
    const name = (await askText(T.nameTitle, T.nameLabel, suggested))?.trim();
    if (!name) return;
    try {
      await create(name);
      setStatus(T.added(name));
    } catch (err) {
      toast(T.addError((err as Error).message ?? String(err)), 'danger');
    }
  }

  function fromImage(ev: Event & { currentTarget: HTMLInputElement }) {
    const file = ev.currentTarget.files?.[0];
    ev.currentTarget.value = '';
    if (file) addCustom(file.name.replace(/\.[^.]+$/, ''), (name) => library.addFromImage(file, name));
  }

  async function fromSelection() {
    const items = annotations.selected();
    if (!items.length) return toast(T.noSelection, 'warning');
    if (items.some((item) => item.pageIndex !== items[0].pageIndex)) return toast(T.samePage, 'warning');
    await annotations.commit(); // el dibujo sale del PDF de EmbedPDF: lo pendiente tiene que estar escrito
    addCustom(T.defaultName, (name) => library.addFromAnnotations(canvas.shown!, items, name));
  }

  // ── Firmas ─────────────────────────────────────────────────────────────
  async function newSignature() {
    const created = await openModal<NewSignature>(SignatureDialog);
    if (!created) return;
    const id = await signatures.add(created.entry, created.keep);
    placeSignature(id);
  }

  const placeSignature = (id: string, initials = false) =>
    arm(() => signatures.place(canvas.shown!, id, initials), TS.placeError);

  async function removeSignature(entry: SignatureEntry) {
    if (await confirmDialog(TS.removeTitle, TS.removeQuestion)) await signatures.remove(entry.id);
  }
</script>

{#snippet grid(items: StampItem[], removable: (item: StampItem) => boolean)}
  <div class="stamp-grid">
    {#each items as item (item.key)}
      <div class="stamp-tile">
        <button class="stamp-tile__button" type="button" title={item.name} onclick={() => place(item)}>
          {#if item.thumb}
            <img class="stamp-tile__img" src={item.thumb} alt={item.name} draggable="false" />
          {:else}
            <span class="stamp-tile__name ellipsis">{item.name}</span>
          {/if}
        </button>
        {#if removable(item)}
          <button class="btn btn--icon btn--sm stamp-tile__remove" type="button" title={T.remove(item.name)}
                  aria-label={T.remove(item.name)} onclick={() => remove(item)}><Icon name="x" size={12} /></button>
        {/if}
      </div>
    {/each}
  </div>
{/snippet}

{#snippet stampsTab()}
  <div class="stamps-tab">
    <p class="caption">{T.hint}</p>
    {#if !library.loaded}
      <p class="muted">{T.loading}</p>
    {:else}
      <h3 class="section-title">{T.standard}</h3>
      {@render grid(library.standard, () => false)}
      <div class="stamps-tab__row">
        <h3 class="section-title">{T.text}</h3>
        <span class="grow"></span>
        <button class="btn btn--ghost btn--sm" type="button" title={T.newTextTip} onclick={manageLegends}>
          <Icon name="type" />{T.newText}
        </button>
      </div>
      {@render grid(library.text, (item) => Boolean(item.legendId))}
      <div class="stamps-tab__row">
        <h3 class="section-title">{T.custom}</h3>
      </div>
      {#if library.custom.length}
        {@render grid(library.custom, (item) => item.library === CUSTOM)}
      {:else}
        <p class="muted">{T.emptyCustom}</p>
      {/if}
      <div class="stamps-tab__actions">
        <button class="btn btn--sm" type="button" title={T.fromImageTip} onclick={() => picker!.click()}>
          <Icon name="image" />{T.fromImage}
        </button>
        <button class="btn btn--sm" type="button" title={T.fromSelectionTip} onclick={fromSelection}>
          <Icon name="pointer" />{T.fromSelection}
        </button>
        <input bind:this={picker} type="file" accept={IMAGES} hidden onchange={fromImage} />
      </div>
    {/if}
  </div>
{/snippet}

{#snippet signaturesTab()}
  <div class="stamps-tab">
    <p class="caption">{TS.hint}</p>
    <button class="btn btn--primary btn--block" type="button" onclick={newSignature}><Icon name="plus" />{TS.create}</button>
    {#each signatures.entries as entry (entry.id)}
      {@const kept = signatures.kept.has(entry.id)}
      <div class="signature-card">
        <div class="signature-card__previews">
          <button class="stamp-tile__button signature-card__preview" type="button" title={TS.placeSignature}
                  onclick={() => placeSignature(entry.id)}>
            <img src={entry.signature.previewDataUrl} alt={TS.signature} draggable="false" />
          </button>
          {#if entry.initials}
            <button class="stamp-tile__button signature-card__preview signature-card__preview--initials" type="button"
                    title={TS.placeInitials} onclick={() => placeSignature(entry.id, true)}>
              <img src={entry.initials.previewDataUrl} alt={TS.initials} draggable="false" />
            </button>
          {/if}
        </div>
        <div class="signature-card__row">
          <span class="caption" class:signature-card__kept={kept}>{kept ? TS.kept : TS.session}</span>
          <span class="grow"></span>
          <button class="btn btn--icon btn--sm" class:is-checked={kept} type="button" title={kept ? TS.forget : TS.keep}
                  aria-label={kept ? TS.forget : TS.keep} aria-pressed={kept} onclick={() => signatures.keep(entry.id, !kept)}>
            <Icon name="save" />
          </button>
          <button class="btn btn--icon btn--sm" type="button" title={TS.remove} aria-label={TS.remove}
                  onclick={() => removeSignature(entry)}><Icon name="trash" /></button>
        </div>
      </div>
    {:else}
      <p class="muted">{TS.empty}</p>
    {/each}
  </div>
{/snippet}

<div class="stamps-panel">
  <div class="stamps-panel__head">
    <span class="stamps-panel__icon"><Icon name="stamp" size={20} /></span>
    <h2 class="heading">{T.title}</h2>
    <span class="grow"></span>
    <button class="btn btn--icon btn--sm" type="button" title={T.close} aria-label={T.close} onclick={close}><Icon name="x" /></button>
  </div>
  <SubTabs bind:current={tab} tabs={[
    { label: T.tab, icon: 'stamp', panel: stampsTab },
    { label: TS.tab, icon: 'signature', panel: signaturesTab },
  ]} />
</div>
