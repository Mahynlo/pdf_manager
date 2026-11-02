<!--
  «Gestionar Perfiles de Censura» (ProfileManagerDialog en Qt): buscar, crear,
  renombrar y eliminar perfiles. Resuelve el id del perfil a cargar, o null.
  `active`: id del perfil en uso; `refresh()`: el panel vuelve a pedir su estado.
-->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { askText, confirmDialog, toast } from '$lib/ui.ts';
  import { t } from '$texts';

  /** Perfil de `redact.profiles`. */
  interface Profile {
    id: string;
    name: string;
    terms: number;
  }

  const T = t.viewer.redact.profiles;

  let { active, refresh, done }: {
    active: string | undefined;
    refresh: () => void;
    done: (id: string | null) => void;
  } = $props();
  let dialog: Dialog;
  let search: HTMLInputElement;
  let query = $state('');
  let profiles = $state.raw<Profile[]>([]);
  let selected = $state<string | null>(null);
  let result: string | null = null;

  const selectedName = () => profiles.find((p) => p.id === selected)?.name ?? '';

  async function reload() {
    try {
      profiles = await call<Profile[]>('redact.profiles', query);
      if (!profiles.some((p) => p.id === selected)) selected = null;
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  async function act(request: Promise<unknown>) {
    try {
      await request;
      reload();
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  function load(id: string | null) {
    if (!id) return;
    result = id;
    dialog.close();
  }

  async function create() {
    const name = await askText(T.createTitle, T.createLabel);
    if (name?.trim()) act(call('redact.create_profile', name));
  }

  async function rename() {
    if (!selected) return;
    const name = await askText(T.renameTitle, T.renameLabel, selectedName());
    if (name?.trim()) act(call('redact.rename_profile', selected, name));
  }

  async function remove() {
    if (!selected) return;
    if (await confirmDialog(T.removeTitle, T.removeQuestion(selectedName()))) {
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
    <h2 class="heading redact-heading">{T.title}</h2>
    <span class="grow"></span>
    <button class="btn btn--primary" type="button" onclick={create}><Icon name="plus" />{T.create}</button>
  </div>
  <input bind:this={search} bind:value={query} class="input" type="search" placeholder={T.search}
         aria-label={T.searchLabel} oninput={reload} />
  <div class="redact-profiles" role="listbox" aria-label={T.list}>
    {#each profiles as p (p.id)}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="redact-profile" class:is-selected={p.id === selected} role="option" aria-selected={p.id === selected}
           tabindex="-1" onclick={() => (selected = p.id)} ondblclick={() => load(p.id)}>
        <span class="grow">{p.name}{#if p.id === active}<strong class="redact-profile__active">{T.active}</strong>{/if}</span>
        <span class="caption">{T.terms(p.terms)}</span>
      </div>
    {:else}
      <p class="muted redact-terms__empty">{T.empty}</p>
    {/each}
  </div>
  <div class="dialog__actions">
    <button class="btn btn--primary" type="button" onclick={() => load(selected)}><Icon name="download" />{T.load}</button>
    <button class="btn" type="button" onclick={rename}><Icon name="pencil" />{T.rename}</button>
    <button class="btn btn--danger" type="button" onclick={remove}><Icon name="trash" />{T.remove}</button>
    <span class="grow"></span>
    <button class="btn" type="button" onclick={() => dialog.close()}>{T.close}</button>
  </div>
</Dialog>
