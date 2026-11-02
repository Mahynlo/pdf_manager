<!-- Página de la vista previa ampliada, con navegación (← →). `pages`: [{ id, page, name }]. -->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import Dialog from '$lib/components/Dialog.svelte';
  import Icon from '$lib/Icon.svelte';
  import { t } from '$texts';

  const T = t.merge.lightbox;

  let { pages, start, done }: {
    pages: { id: number; page: number; name: string }[];
    start: number;
    done: () => void;
  } = $props();
  let dialog: Dialog;
  // svelte-ignore state_referenced_locally
  let index = $state(start); // página inicial; luego se navega
  let src = $state('');
  let error = $state('');

  const current = $derived(pages[index]);

  // Ignora respuestas de páginas ya dejadas atrás.
  $effect(() => {
    const i = index;
    const { id, page } = pages[i];
    error = '';
    call<string>('merge.page_image', id, page)
      .then((url) => i === index && (src = url))
      .catch((err: Error) => (error = err.message));
  });

  function show(i: number) {
    if (i >= 0 && i < pages.length) index = i;
  }

  function onkeydown(ev: KeyboardEvent) {
    if (ev.key === 'ArrowLeft') show(index - 1);
    if (ev.key === 'ArrowRight') show(index + 1);
  }
</script>

<Dialog bind:this={dialog} class="lightbox" onclose={() => done()} {onkeydown}>
  <div class="dialog__head">
    <button class="btn" type="button" disabled={index === 0} onclick={() => show(index - 1)}>
      <Icon name="chevron-left" />{T.prev}
    </button>
    <span class="lightbox__info ellipsis">
      {error || T.info(current.name, current.page + 1, index + 1, pages.length)}
    </span>
    <button class="btn" type="button" disabled={index === pages.length - 1} onclick={() => show(index + 1)}>
      {T.next}<Icon name="chevron-right" />
    </button>
  </div>
  <div class="lightbox__stage"><img alt="" src={src || undefined} /></div>
  <div class="dialog__actions"><button class="btn" type="button" onclick={() => dialog.close()}>{T.close}</button></div>
</Dialog>
