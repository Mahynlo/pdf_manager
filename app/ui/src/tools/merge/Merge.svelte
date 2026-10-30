<!--
  Herramienta Combinar. El estado vive en el backend (servicio "merge"): cada acción
  devuelve el estado completo y la vista se repinta a partir de él.
-->
<script>
  import { onDestroy } from 'svelte';
  import { call, on } from '$lib/api.js';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import { fileName } from '$lib/dom.js';
  import Icon from '$lib/Icon.svelte';
  import { ThumbLoader } from '$lib/thumbs.js';
  import { askPassword, openModal, toast } from '$lib/ui.js';
  import EntryCard from './EntryCard.svelte';
  import Lightbox from './Lightbox.svelte';
  import PreviewGrid from './PreviewGrid.svelte';

  let { tool } = $props();

  let merge = $state.raw({ entries: [], preview: [], output: null, busy: false, last_result: null });
  let options = $state({ bookmarks: true, duplex: false, optimize: true });
  let merging = $state(false);
  let progress = $state(0);

  const thumbs = new ThumbLoader((id, pages) => call('merge.thumbnails', id, pages));

  /** Llama al backend mostrando el error como aviso; devuelve undefined si falla. */
  async function request(method, ...args) {
    try {
      return await call(`merge.${method}`, ...args);
    } catch (err) {
      toast(err.message, 'danger');
      return undefined;
    }
  }

  async function update(method, ...args) {
    const next = await request(method, ...args);
    if (next) merge = next;
  }

  async function load(method) {
    const res = await request(method);
    if (!res) return;
    merge = res.state;
    for (const message of res.errors) toast(message, 'danger');
    for (const path of res.locked) {
      await askPassword(fileName(path), async (password) => {
        try {
          merge = await call('merge.unlock', path, password);
          return null;
        } catch (err) {
          return err.message;
        }
      });
    }
  }

  const actions = {
    toggle: (id, page) => update('toggle', id, page),
    selectAll: (id, value) => update('select_all', id, value),
    invert: (id) => update('invert', id),
    setRange: (id, text) => update('set_range', id, text),
    rotate: (id, delta) => update('rotate', id, delta),
    move: (id, delta) => update('move', id, delta),
    remove: (id) => update('remove', id),
  };

  function openPage(index) {
    const byId = new Map(merge.entries.map((e) => [e.id, e]));
    const pages = merge.preview.map(([id, page]) => ({ id, page, name: byId.get(id).name }));
    openModal(Lightbox, { pages, start: index });
  }

  async function runMerge() {
    merging = true;
    progress = 0;
    const res = await request('merge', { ...options });
    merging = false;
    if (res) {
      merge = res.state;
      toast(`Se combinaron ${res.count} páginas en ${fileName(res.path)}`, 'success');
    }
  }

  $effect(() => on('merge:progress', ({ done, total }) => (progress = (100 * done) / total)));

  update('state');

  onDestroy(() => {
    thumbs.disconnect();
    call('merge.clear'); // libera los documentos abiertos al cerrar la pestaña
  });
</script>

{#snippet button(icon, label, onclick, { cls = '', title = undefined, disabled = false } = {})}
  <button class="btn {cls}" type="button" {onclick} {title} {disabled}><Icon name={icon} />{label}</button>
{/snippet}

<div class="merge">
  <ToolHeader emoji={tool.emoji} color={tool.color} title="Combinar PDFs"
              subtitle="Selecciona, reordena y combina páginas de múltiples documentos en un solo PDF optimizado" />
  <div class="merge__body">
    <section class="merge__column">
      <div class="section-head">
        <h2 class="heading">Paso 1: Documentos Fuente</h2>
        <span class="spacer"></span>
        {@render button('arrow-down-a-z', 'A-Z', () => update('sort_by_name'), { cls: 'btn--sm', title: 'Ordenar por nombre de archivo (A-Z)' })}
        {@render button('arrow-up-down', 'Invertir', () => update('reverse'), { cls: 'btn--sm', title: 'Invertir orden de los documentos' })}
        {@render button('eraser', 'Limpiar', () => update('clear'), { cls: 'btn--sm', title: 'Quitar todos los documentos' })}
      </div>
      <div class="load-row">
        {@render button('file-plus', 'Cargar PDFs...', () => load('pick_files'), { cls: 'btn--success' })}
        {@render button('folder-plus', 'Añadir Carpeta...', () => load('pick_folder'))}
      </div>
      {#if merge.entries.length}
        <div class="entry-list">
          {#each merge.entries as entry, index (entry.id)}
            <EntryCard {entry} {thumbs} {actions} first={index === 0} last={index === merge.entries.length - 1} />
          {/each}
        </div>
      {:else}
        <div class="empty"><Icon name="files" size={32} /><p>Carga PDFs o una carpeta para empezar.</p></div>
      {/if}
    </section>

    <section class="merge__column card merge__result">
      <div class="section-head">
        <Icon name="eye" size={18} />
        <h2 class="heading">Paso 2: Vista previa del resultado</h2>
        <span class="spacer"></span>
        <span class="caption">{merge.preview.length} página(s)</span>
      </div>
      <p class="hint">Arrastra para reordenar o haz doble clic para ampliar una página</p>
      <PreviewGrid {merge} {thumbs} onReorder={(keys) => update('reorder', keys)} onOpen={openPage} />
      <div class="merge__options">
        <Checkbox label="Crear marcadores (TOC)" bind:checked={options.bookmarks}
                  title="Crea un índice con los nombres de los documentos originales" />
        <Checkbox label="Ajuste Dúplex (Doble cara)" bind:checked={options.duplex}
                  title="Inserta una página en blanco si un documento termina en página impar" />
        <Checkbox label="Optimizar PDF" bind:checked={options.optimize}
                  title="Comprime y limpia objetos redundantes en el PDF resultante" />
      </div>
      <div class="merge__output">
        <Icon name="save" />
        <span class="ellipsis" title={merge.output ?? ''}>{merge.output ?? 'Sin ruta de salida seleccionada'}</span>
        {@render button('folder', 'Cambiar Destino...', () => update('choose_output'), { cls: 'btn--sm' })}
      </div>
      <div class="progress" hidden={!merging}><span style:width="{progress}%"></span></div>
      <div class="merge__actions">
        {@render button('files', 'Combinar y Guardar', runMerge,
                        { cls: 'btn--primary btn--lg', disabled: merging || merge.busy || !merge.preview.length })}
        {@render button('eye', 'Ver PDF Combinado', () => request('open_result'), { cls: 'btn--lg', disabled: !merge.last_result })}
        {@render button('folder-open', 'Abrir Carpeta', () => request('open_output_folder'),
                        { cls: 'btn--lg', title: 'Abrir carpeta de destino', disabled: !merge.output })}
      </div>
    </section>
  </div>
</div>
