<!-- Pide un texto (askText). Enter acepta; con `multiline`, Ctrl+Enter. -->
<script lang="ts">
  import Dialog from './Dialog.svelte';

  let { title, label, initial = '', multiline = false, done }: {
    title: string;
    label: string;
    initial?: string;
    multiline?: boolean;
    done: (text: string | null) => void;
  } = $props();
  let dialog: Dialog;
  let input = $state<HTMLInputElement | HTMLTextAreaElement>();
  // svelte-ignore state_referenced_locally
  let value = $state(initial); // texto inicial; luego lo edita el usuario
  let result: string | null = null;

  $effect(() => {
    input!.focus();
    input!.select();
  });

  function accept() {
    result = value;
    dialog.close();
  }

  function onkeydown(ev: KeyboardEvent) {
    if (ev.key === 'Enter' && (!multiline || ev.ctrlKey)) {
      ev.preventDefault();
      accept();
    }
  }
</script>

<Dialog bind:this={dialog} class="ask-text" onclose={() => done(result)}>
  <h2 class="heading">{title}</h2>
  <label class="field">
    <span class="caption">{label}</span>
    {#if multiline}
      <textarea bind:this={input} bind:value class="input dialog__textarea" rows="5" aria-label={label} {onkeydown}></textarea>
    {:else}
      <input bind:this={input} bind:value class="input" type="text" aria-label={label} {onkeydown} />
    {/if}
  </label>
  <div class="dialog__actions">
    <button class="btn" type="button" onclick={() => dialog.close()}>Cancelar</button>
    <button class="btn btn--primary" type="button" onclick={accept}>Aceptar</button>
  </div>
</Dialog>
