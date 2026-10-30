<!-- Archivos recientes de Inicio: abrir, quitar y menú contextual. -->
<script>
  import { call, on } from '$lib/api.js';
  import Icon from '$lib/Icon.svelte';
  import { openMenuAt } from '$lib/menu.svelte.js';
  import { toast } from '$lib/ui.js';
  import { shell } from './shell.svelte.js';

  let files = $state([]);

  async function run(method, ...args) {
    try {
      files = await call(`documents.${method}`, ...args);
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  const refresh = () => run('recent');
  $effect(() => on('recent:changed', refresh));
  refresh();

  const open = (file) => shell.openDocument(file.path);
  const remove = (file) => run('remove_recent', file.path);

  function contextMenu(ev, file) {
    ev.preventDefault();
    openMenuAt(ev.clientX, ev.clientY, [
      { label: 'Abrir documento', icon: 'folder-open', onSelect: () => open(file) },
      { label: 'Abrir ubicación en Explorador', icon: 'folder', onSelect: () => call('documents.reveal', file.path) },
      { label: 'Copiar ruta del archivo', icon: 'copy', onSelect: () => navigator.clipboard.writeText(file.path) },
      'separator',
      { label: 'Quitar de la lista', icon: 'x', onSelect: () => remove(file) },
    ]);
  }
</script>

<aside class="recent">
  <div class="recent__head">
    <Icon name="clock" size={18} />
    <h2 class="recent__title">Archivos recientes</h2>
    <button class="btn btn--ghost btn--sm" type="button" disabled={!files.length} onclick={() => run('clear_recent')}>
      Limpiar
    </button>
  </div>
  <div class="recent__list">
    {#each files as file (file.path)}
      <div class="recent-row" role="button" tabindex="0" title={file.path} onclick={() => open(file)}
           onkeydown={(ev) => ev.key === 'Enter' && open(file)} oncontextmenu={(ev) => contextMenu(ev, file)}>
        <span class="recent-row__badge"><Icon name="file-text" size={18} /></span>
        <span class="recent-row__info">
          <span class="recent-row__name ellipsis">{file.name}</span>
          <span class="caption ellipsis">{file.folder}</span>
        </span>
        <button class="btn btn--icon btn--sm" type="button" title="Quitar de recientes"
                onclick={(ev) => { ev.stopPropagation(); remove(file); }}>
          <Icon name="x" size={14} />
        </button>
      </div>
    {:else}
      <p class="recent__empty">Sin archivos recientes</p>
    {/each}
  </div>
</aside>
