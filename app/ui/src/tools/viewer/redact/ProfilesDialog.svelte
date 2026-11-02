<!--
  «Gestionar Perfiles de Censura» (ProfileManagerDialog en Qt): buscar, crear,
  renombrar y eliminar perfiles. Resuelve el id del perfil a cargar, o null.
  `active`: id del perfil en uso; `refresh()`: el panel vuelve a pedir su estado.
-->
<script>
  import { call } from '$lib/api.js';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { askText, confirmDialog, toast } from '$lib/ui.js';

  let { active, refresh, done } = $props();
  let dialog;
  let search;
  let query = $state('');
  let profiles = $state.raw([]);
  let selected = $state(null);
  let result = null;

  const selectedName = () => profiles.find((p) => p.id === selected)?.name ?? '';

  async function reload() {
    try {
      profiles = await call('redact.profiles', query);
      if (!profiles.some((p) => p.id === selected)) selected = null;
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  async function act(request) {
    try {
      await request;
      reload();
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  function load(id) {
    if (!id) return;
    result = id;
    dialog.close();
  }

  async function create() {
    const name = await askText('Nuevo Perfil', 'Introduce el nombre del nuevo perfil de censura:');
    if (name?.trim()) act(call('redact.create_profile', name));
  }

  async function rename() {
    if (!selected) return;
    const name = await askText('Renombrar Perfil', 'Nuevo nombre:', selectedName());
    if (name?.trim()) act(call('redact.rename_profile', selected, name));
  }

  async function remove() {
    if (!selected) return;
    if (await confirmDialog('Eliminar Perfil', `¿Estás seguro de que deseas eliminar el perfil «${selectedName()}»?`)) {
      await act(call('redact.delete_profile', selected));
      refresh(); // si era el activo, el panel deja de mostrarlo
    }
  }

  $effect(() => search.focus());
  reload();
</script>

<Dialog bind:this={dialog} class="redact-profiles-dialog" onclose={() => done(result)}>
  <div class="dialog__head">
    <span class="redact-panel__icon"><Icon name="folder" size={20} /></span>
    <h2 class="heading redact-heading">Perfiles Guardados</h2>
    <span class="grow"></span>
    <button class="btn btn--primary" type="button" onclick={create}><Icon name="plus" />Nuevo Perfil</button>
  </div>
  <input bind:this={search} bind:value={query} class="input" type="search" placeholder="Buscar perfil por nombre o términos..."
         aria-label="Buscar perfil" oninput={reload} />
  <div class="redact-profiles" role="listbox" aria-label="Perfiles guardados">
    {#each profiles as p (p.id)}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="redact-profile" class:is-selected={p.id === selected} role="option" aria-selected={p.id === selected}
           tabindex="-1" onclick={() => (selected = p.id)} ondblclick={() => load(p.id)}>
        <span class="grow">{p.name}{#if p.id === active}<strong class="redact-profile__active"> [ACTIVO]</strong>{/if}</span>
        <span class="caption">{p.terms} términos</span>
      </div>
    {:else}
      <p class="muted redact-terms__empty">Sin perfiles guardados</p>
    {/each}
  </div>
  <div class="dialog__actions">
    <button class="btn btn--primary" type="button" onclick={() => load(selected)}><Icon name="download" />Cargar en Visor</button>
    <button class="btn" type="button" onclick={rename}><Icon name="pencil" />Renombrar</button>
    <button class="btn btn--danger" type="button" onclick={remove}><Icon name="trash" />Eliminar</button>
    <span class="grow"></span>
    <button class="btn" type="button" onclick={() => dialog.close()}>Cerrar</button>
  </div>
</Dialog>
