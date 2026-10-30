<!-- Pide la contraseña de un PDF (askPassword); `tryUnlock(pwd)` → null o mensaje de error. -->
<script>
  import Icon from '../Icon.svelte';
  import Dialog from './Dialog.svelte';
  import PasswordField from './PasswordField.svelte';

  let { name, tryUnlock, done } = $props();
  let dialog;
  let field;
  let password = $state('');
  let error = $state('');
  let busy = $state(false);
  let unlocked = false;

  $effect(() => field.focus());

  async function submit(ev) {
    ev.preventDefault();
    busy = true;
    const message = await tryUnlock(password);
    busy = false;
    if (message) {
      error = message;
      field.select();
    } else {
      unlocked = true;
      dialog.close();
    }
  }
</script>

<Dialog bind:this={dialog} onclose={() => done(unlocked)}>
  <form class="password-form" onsubmit={submit}>
    <div class="dialog__head"><Icon name="lock" size={20} /><h2 class="heading">PDF protegido</h2></div>
    <p class="muted">«{name}» necesita contraseña para abrirse.</p>
    <PasswordField bind:this={field} bind:value={password} placeholder="Contraseña" />
    <p class="dialog__error">{error}</p>
    <div class="dialog__actions">
      <button class="btn" type="button" onclick={() => dialog.close()}>Cancelar</button>
      <button class="btn btn--primary" type="submit" disabled={busy}><Icon name="lock-open" />Desbloquear</button>
    </div>
  </form>
</Dialog>

<style>
  /* El formulario no rompe la columna de .dialog__body. */
  .password-form {
    display: contents;
  }
</style>
