<!--
  Herramienta Combinar. El estado vive en el backend (servicio "merge"): cada acción
  devuelve el estado completo y la vista se repinta a partir de él.
-->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { call, on } from '$lib/api.ts';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import { fileName } from '$lib/dom.ts';
  import Icon from '$lib/Icon.svelte';
  import { ThumbLoader } from '$lib/thumbs.ts';
  import { askPassword, openModal, toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { Tool } from '../../shell/tools.ts';
  import EntryCard from './EntryCard.svelte';
  import Lightbox from './Lightbox.svelte';
  import PreviewGrid from './PreviewGrid.svelte';
  import type { EntryActions, MergeState } from './types.ts';

  const T = t.merge;

  let { tool }: { tool: Tool } = $props();

  let merge = $state.raw<MergeState>({ entries: [], preview: [], output: null, busy: false, last_result: null });
  let options = $state({ bookmarks: true, duplex: false, optimize: true });
  let merging = $state(false);
  let progress = $state(0);

  const thumbs = new ThumbLoader((id, pages) => call('merge.thumbnails', id, pages));

  /** Llama al backend mostrando el error como aviso; devuelve undefined si falla. */
  async function request<R = MergeState>(method: string, ...args: unknown[]): Promise<R | undefined> {
    try {
      return await call<R>(`merge.${method}`, ...args);
    } catch (err) {
      toast((err as Error).message, 'danger');
      return undefined;
    }
  }

  async function update(method: string, ...args: unknown[]) {
    const next = await request(method, ...args);
    if (next) merge = next;
  }

  async function load(method: string) {
    const res = await request<{ state: MergeState; locked: string[]; errors: string[] }>(method);
    if (!res) return;
    merge = res.state;
    for (const message of res.errors) toast(message, 'danger');
    for (const path of res.locked) {
      await askPassword(fileName(path), async (password) => {
        try {
          merge = await call<MergeState>('merge.unlock', path, password);
          return null;
        } catch (err) {
          return (err as Error).message;
        }
      });
    }
  }

  const actions: EntryActions = {
    toggle: (id, page) => update('toggle', id, page),
    selectAll: (id, value) => update('select_all', id, value),
    invert: (id) => update('invert', id),
    setRange: (id, text) => update('set_range', id, text),
    rotate: (id, delta) => update('rotate', id, delta),
    move: (id, delta) => update('move', id, delta),
    remove: (id) => update('remove', id),
  };

  function openPage(index: number) {
    const byId = new Map(merge.entries.map((e) => [e.id, e]));
    const pages = merge.preview.map(([id, page]) => ({ id, page, name: byId.get(id)!.name }));
    openModal(Lightbox, { pages, start: index });
  }

  async function runMerge() {
    merging = true;
    progress = 0;
    const res = await request<{ state: MergeState; count: number; path: string }>('merge', { ...options });
    merging = false;
    if (res) {
      merge = res.state;
      toast(T.result.done(res.count, fileName(res.path)), 'success');
    }
  }

  $effect(() => on<{ done: number; total: number }>('merge:progress', ({ done, total }) => (progress = (100 * done) / total)));

  update('state');

  onDestroy(() => {
    thumbs.disconnect();
    call('merge.clear'); // libera los documentos abiertos al cerrar la pestaña
  });
</script>

{#snippet button(icon: string, label: string, onclick: () => unknown,
                 { cls = '', title = undefined, disabled = false }: { cls?: string; title?: string; disabled?: boolean } = {})}
  <button class="btn {cls}" type="button" {onclick} {title} {disabled}><Icon name={icon} />{label}</button>
{/snippet}

<div class="merge">
  <ToolHeader emoji={tool.emoji} color={tool.color} title={T.title} subtitle={T.subtitle} />
  <div class="merge__body">
    <section class="merge__column">
      <div class="section-head">
        <h2 class="heading">{T.sources.title}</h2>
        <span class="spacer"></span>
        {@render button('arrow-down-a-z', T.sources.sort, () => update('sort_by_name'), { cls: 'btn--sm', title: T.sources.sortTip })}
        {@render button('arrow-up-down', T.sources.reverse, () => update('reverse'), { cls: 'btn--sm', title: T.sources.reverseTip })}
        {@render button('eraser', T.sources.clear, () => update('clear'), { cls: 'btn--sm', title: T.sources.clearTip })}
      </div>
      <div class="load-row">
        {@render button('file-plus', T.sources.load, () => load('pick_files'), { cls: 'btn--success' })}
        {@render button('folder-plus', T.sources.addFolder, () => load('pick_folder'))}
      </div>
      {#if merge.entries.length}
        <div class="entry-list">
          {#each merge.entries as entry, index (entry.id)}
            <EntryCard {entry} {thumbs} {actions} first={index === 0} last={index === merge.entries.length - 1} />
          {/each}
        </div>
      {:else}
        <div class="empty"><Icon name="files" size={32} /><p>{T.sources.empty}</p></div>
      {/if}
    </section>

    <section class="merge__column card merge__result">
      <div class="section-head">
        <Icon name="eye" size={18} />
        <h2 class="heading">{T.result.title}</h2>
        <span class="spacer"></span>
        <span class="caption">{T.result.count(merge.preview.length)}</span>
      </div>
      <p class="hint">{T.result.hint}</p>
      <PreviewGrid {merge} {thumbs} onReorder={(keys) => update('reorder', keys)} onOpen={openPage} />
      <div class="merge__options">
        <Checkbox label={T.result.bookmarks} bind:checked={options.bookmarks} title={T.result.bookmarksTip} />
        <Checkbox label={T.result.duplex} bind:checked={options.duplex} title={T.result.duplexTip} />
        <Checkbox label={T.result.optimize} bind:checked={options.optimize} title={T.result.optimizeTip} />
      </div>
      <div class="merge__output">
        <Icon name="save" />
        <span class="ellipsis" title={merge.output ?? ''}>{merge.output ?? T.result.noOutput}</span>
        {@render button('folder', T.result.changeOutput, () => update('choose_output'), { cls: 'btn--sm' })}
      </div>
      <div class="progress" hidden={!merging}><span style:width="{progress}%"></span></div>
      <div class="merge__actions">
        {@render button('files', T.result.merge, runMerge,
                        { cls: 'btn--primary btn--lg', disabled: merging || merge.busy || !merge.preview.length })}
        {@render button('eye', T.result.open, () => request('open_result'), { cls: 'btn--lg', disabled: !merge.last_result })}
        {@render button('folder-open', T.result.openFolder, () => request('open_output_folder'),
                        { cls: 'btn--lg', title: T.result.openFolderTip, disabled: !merge.output })}
      </div>
    </section>
  </div>
</div>
