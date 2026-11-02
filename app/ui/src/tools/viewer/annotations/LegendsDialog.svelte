<!--
  Gestor de leyendas y sellos (legends_dialog.py en Qt): lista, crear, eliminar y
  elegir uno para insertar. Resuelve { text, color, font_size } a insertar, o null.
-->
<script>
  import { call } from '$lib/api.js';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.js';
  import { DEFAULT_COLOR, DEFAULT_SIZE } from './stamps.js';

  let { done } = $props();
  let dialog;
  let legends = $state.raw([]);
  let selected = $state(null);
  let text = $state('');
  let size = $state(DEFAULT_SIZE);
  let color = $state(DEFAULT_COLOR);
  let result = null;

  const fontSize = $derived(Number(size) || DEFAULT_SIZE);

  async function run(request) {
    try {
      legends = await request;
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  function choose(legend) {
    selected = legend;
    text = legend.text;
    size = legend.font_size;
    color = legend.color.toLowerCase();
  }

  async function remove() {
    if (!selected) return;
    await run(call('legends.delete', selected.id));
    selected = null;
  }

  function create() {
    if (text.trim()) run(call('legends.create', text, color, fontSize));
  }

  function insert() {
    const value = text.trim();
    if (!value) return;
    if (selected?.text === value) call('legends.used', selected.id).catch(() => {});
    result = { text: value, color: color.toUpperCase(), font_size: fontSize };
    dialog.close();
  }

  run(call('legends.all'));
</script>

<Dialog bind:this={dialog} class="legends-dialog" onclose={() => done(result)}>
  <h2 class="heading">Gestor de Leyendas y Sellos de Texto</h2>
  <div class="legends">
    <div class="legends__side">
      <h3 class="section-title">Sellos y Leyendas Guardadas:</h3>
      <div class="legends__list" role="listbox" aria-label="Sellos y leyendas guardadas">
        {#each legends as legend (legend.id)}
          <button class="legends__item" class:is-active={selected?.id === legend.id} type="button" role="option"
                  aria-selected={selected?.id === legend.id} onclick={() => choose(legend)}>
            <Icon name="tag" /><span class="ellipsis">{legend.name}</span>
          </button>
        {:else}
          <p class="muted legends__empty">No hay leyendas guardadas</p>
        {/each}
      </div>
      <button class="btn" type="button" onclick={remove}><Icon name="trash" />Eliminar</button>
    </div>
    <div class="legends__editor">
      <h3 class="section-title">Crear / Editar Sello:</h3>
      <label class="legends__row"><span>Texto:</span>
        <input bind:value={text} class="input" type="text" placeholder="Ej: PAGADO, ANULADO..." />
      </label>
      <label class="legends__row"><span>Tamaño (pt):</span>
        <input bind:value={size} class="input legends__size" type="number" min="8" max="72" />
      </label>
      <label class="legends__row"><span>Color:</span>
        <input bind:value={color} class="legends__color" type="color" aria-label="Color" />
      </label>
      <div class="legends__preview" style:color style:border-color={color} style:font-size="{fontSize}px">{text.trim() || 'TEXTO'}</div>
      <div class="dialog__actions">
        <button class="btn" type="button" onclick={create}><Icon name="plus" />Guardar Nuevo</button>
        <button class="btn btn--primary" type="button" onclick={insert}><Icon name="tag" />Insertar en Visor</button>
      </div>
    </div>
  </div>
  <div class="dialog__actions"><button class="btn" type="button" onclick={() => dialog.close()}>Cerrar</button></div>
</Dialog>
