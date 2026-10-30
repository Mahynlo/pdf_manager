<!-- Pide un texto (askText). Enter acepta; con `multiline`, Ctrl+Enter. -->
<script>
  import Dialog from './Dialog.svelte';

  let { title, label, initial = '', multiline = false, done } = $props();
  let dialog;
  let input = $state();
  // svelte-ignore state_referenced_locally
  let value = $state(initial); // texto inicial; luego lo edita el usuario
  let result = null;

  $effect(() => {
    input.focus();
    input.select();
  });

  function accept() {
    result = value;
    dialog.close();
  }

  function onkeydown(ev) {
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
