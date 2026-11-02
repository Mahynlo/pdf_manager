<!-- Pide la contraseña de un PDF (askPassword); `tryUnlock(pwd)` → null o mensaje de error. -->
<script lang="ts">
  import Icon from '../Icon.svelte';
  import Dialog from './Dialog.svelte';
  import PasswordField from './PasswordField.svelte';
  import { t } from '$texts';

  const T = t.common.password;

  let { name, tryUnlock, done }: {
    name: string;
    tryUnlock: (password: string) => Promise<string | null>;
    done: (unlocked: boolean) => void;
  } = $props();
  let dialog: Dialog;
  let field: PasswordField;
  let password = $state('');
  let error = $state('');
  let busy = $state(false);
  let unlocked = false;

  $effect(() => field.focus());

  async function submit(ev: SubmitEvent) {
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
    <div class="dialog__head"><Icon name="lock" size={20} /><h2 class="heading">{T.title}</h2></div>
    <p class="muted">{T.needed(name)}</p>
    <PasswordField bind:this={field} bind:value={password} placeholder={T.placeholder} />
    <p class="dialog__error">{error}</p>
    <div class="dialog__actions">
      <button class="btn" type="button" onclick={() => dialog.close()}>{t.common.cancel}</button>
      <button class="btn btn--primary" type="submit" disabled={busy}><Icon name="lock-open" />{T.unlock}</button>
    </div>
  </form>
</Dialog>

<style>
  /* El formulario no rompe la columna de .dialog__body. */
  .password-form {
    display: contents;
  }
</style>
