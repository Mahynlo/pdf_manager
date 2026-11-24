<!-- Archivos recientes de Inicio: abrir, quitar y menú contextual. -->
<script lang="ts">
  import { call, on } from '$lib/api.ts';
  import Icon from '$lib/Icon.svelte';
  import { openMenuAt } from '$lib/menu.svelte.ts';
  import type { RecentFile } from '$lib/types.ts';
  import { toast } from '$lib/ui.ts';
  import { shell } from './shell.svelte.ts';
  import { t } from '$texts';

  const T = t.shell.recent;
  // En el navegador la ruta es interna (/files/3/…): no se muestra su carpeta, ni hay carpeta que abrir.
  const BROWSER = import.meta.env.MODE === 'browser';

  let files = $state<RecentFile[]>([]);

  async function run(method: string, ...args: unknown[]) {
    try {
      files = await call<RecentFile[]>(`documents.${method}`, ...args);
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  const refresh = () => run('recent');
  $effect(() => on('recent:changed', refresh));
  refresh();

  const NUMBER = new Intl.NumberFormat('es', { maximumFractionDigits: 1 });
  /** «840 KB», «12,4 MB». */
  function size(bytes: number): string {
    const kb = bytes / 1024;
    return kb < 1024 ? `${NUMBER.format(Math.max(1, Math.round(kb)))} KB` : `${NUMBER.format(kb / 1024)} MB`;
  }
  /** Lo que va bajo el nombre: el tamaño y, en el escritorio, la carpeta. */
  const details = (file: RecentFile) =>
    [file.size == null ? '' : size(file.size), BROWSER ? '' : file.folder].filter(Boolean).join(' · ');

  const open = (file: RecentFile) => shell.openDocument(file.path);
  const remove = (file: RecentFile) => run('remove_recent', file.path);

  function contextMenu(ev: MouseEvent, file: RecentFile) {
    ev.preventDefault();
    openMenuAt(ev.clientX, ev.clientY, [
      { label: T.menu.open, icon: 'folder-open', onSelect: () => open(file) },
      ...(BROWSER ? [] : [
        { label: T.menu.reveal, icon: 'folder', onSelect: () => call('documents.reveal', file.path) },
        { label: T.menu.copyPath, icon: 'copy', onSelect: () => navigator.clipboard.writeText(file.path) },
      ]),
      'separator',
      { label: T.menu.remove, icon: 'x', onSelect: () => remove(file) },
    ]);
  }
</script>

<aside class="recent">
  <div class="recent__head">
    <Icon name="clock" size={16} />
    <h2 class="recent__title">{T.title}</h2>
    <button class="btn btn--ghost btn--sm" type="button" disabled={!files.length} onclick={() => run('clear_recent')}>
      {T.clear}
    </button>
  </div>
  <div class="recent__list">
    {#each files as file (file.path)}
      <div class="recent-row" role="button" tabindex="0" title={BROWSER ? file.name : file.path} onclick={() => open(file)}
           onkeydown={(ev) => ev.key === 'Enter' && open(file)} oncontextmenu={(ev) => contextMenu(ev, file)}>
        <span class="recent-row__badge"><Icon name="file-text" size={18} /></span>
        <span class="recent-row__info">
          <span class="recent-row__name ellipsis">{file.name}</span>
          {#if details(file)}<span class="caption ellipsis">{details(file)}</span>{/if}
        </span>
        <button class="btn btn--icon btn--sm" type="button" title={T.remove}
                onclick={(ev) => { ev.stopPropagation(); remove(file); }}>
          <Icon name="x" size={14} />
        </button>
      </div>
    {:else}
      <p class="recent__empty">{T.empty}</p>
    {/each}
  </div>
</aside>
