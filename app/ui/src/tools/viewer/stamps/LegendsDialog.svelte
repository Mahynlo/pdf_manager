<!--
  Gestor de leyendas y sellos (legends_dialog.py en Qt): lista, crear, eliminar y
  elegir uno para insertar. Resuelve { text, color, font_size } a insertar, o null.
-->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import { DEFAULT_COLOR, DEFAULT_SIZE, type Legend } from './library.svelte.ts';
  import type { TextStamp } from './stamp-pdf.ts';

  const T = t.viewer.stamps.legends;

  let { done }: { done: (stamp: TextStamp | null) => void } = $props();
  let dialog: Dialog;
  let legends = $state.raw<Legend[]>([]);
  let selected = $state<Legend | null>(null);
  let text = $state('');
  let size = $state<number | string>(DEFAULT_SIZE);
  let color = $state(DEFAULT_COLOR);
  let result: TextStamp | null = null;

  const fontSize = $derived(Number(size) || DEFAULT_SIZE);

  async function run(request: Promise<Legend[]>) {
    try {
      legends = await request;
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  function choose(legend: Legend) {
    selected = legend;
    text = legend.text;
    size = legend.font_size;
    color = legend.color.toLowerCase();
  }

  async function remove() {
    if (!selected) return;
    await run(call<Legend[]>('legends.delete', selected.id));
    selected = null;
  }

  function create() {
    if (text.trim()) run(call<Legend[]>('legends.create', text, color, fontSize));
  }

  function insert() {
    const value = text.trim();
    if (!value) return;
    if (selected?.text === value) call('legends.used', selected.id).catch(() => {});
    result = { text: value, color: color.toUpperCase(), font_size: fontSize };
    dialog.close();
  }

  run(call<Legend[]>('legends.all'));
</script>

<Dialog bind:this={dialog} class="legends-dialog" onclose={() => done(result)}>
  <h2 class="heading">{T.title}</h2>
  <div class="legends">
    <div class="legends__side">
      <h3 class="section-title">{T.saved}</h3>
      <div class="legends__list" role="listbox" aria-label={T.saved}>
        {#each legends as legend (legend.id)}
          <button class="legends__item" class:is-active={selected?.id === legend.id} type="button" role="option"
                  aria-selected={selected?.id === legend.id} onclick={() => choose(legend)}>
            <Icon name="tag" /><span class="ellipsis">{legend.name}</span>
          </button>
        {:else}
          <p class="muted legends__empty">{T.empty}</p>
        {/each}
      </div>
      <button class="btn" type="button" onclick={remove}><Icon name="trash" />{T.remove}</button>
    </div>
    <div class="legends__editor">
      <h3 class="section-title">{T.editor}</h3>
      <label class="legends__row"><span>{T.text}</span>
        <input bind:value={text} class="input" type="text" placeholder={T.textPlaceholder} />
      </label>
      <label class="legends__row"><span>{T.size}</span>
        <input bind:value={size} class="input legends__size" type="number" min="8" max="72" />
      </label>
      <label class="legends__row"><span>{T.color}</span>
        <input bind:value={color} class="legends__color" type="color" aria-label={T.colorLabel} />
      </label>
      <div class="legends__preview" style:color style:border-color={color} style:font-size="{fontSize}px">{text.trim() || T.preview}</div>
      <div class="dialog__actions">
        <button class="btn" type="button" onclick={create}><Icon name="plus" />{T.create}</button>
        <button class="btn btn--primary" type="button" onclick={insert}><Icon name="tag" />{T.insert}</button>
      </div>
    </div>
  </div>
  <div class="dialog__actions"><button class="btn" type="button" onclick={() => dialog.close()}>{T.close}</button></div>
</Dialog>
