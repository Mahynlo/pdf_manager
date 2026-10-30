<!-- Pregunta con botones propios (askChoice); el último recibe el foco. -->
<script>
  import Icon from '../Icon.svelte';
  import Dialog from './Dialog.svelte';

  let { title, message, buttons, done } = $props();
  let dialog;
  let actions;
  let choice = null;

  $effect(() => actions.lastElementChild?.focus());

  function pick(value) {
    choice = value;
    dialog.close();
  }
</script>

<Dialog bind:this={dialog} class="confirm" onclose={() => done(choice)}>
  <div class="dialog__head"><Icon name="circle-alert" size={20} /><h2 class="heading">{title}</h2></div>
  <p class="muted dialog__message">{message}</p>
  <div class="dialog__actions" bind:this={actions}>
    {#each buttons as { label, value, tone }, i (i)}
      <button class="btn" class:btn--primary={tone === 'primary'} class:btn--danger={tone === 'danger'}
              type="button" onclick={() => pick(value)}>{label}</button>
    {/each}
  </div>
</Dialog>
