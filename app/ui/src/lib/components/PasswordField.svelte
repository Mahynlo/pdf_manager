<!-- Campo de contraseña con botón para mostrarla (PasswordLineEdit en Qt). -->
<script lang="ts">
  import Icon from '../Icon.svelte';
  import { t } from '$texts';

  const T = t.common.password;

  let { value = $bindable(''), placeholder = '', onenter }: { value?: string; placeholder?: string; onenter?: () => void } = $props();
  let input: HTMLInputElement;
  let shown = $state(false);

  export const focus = () => input.focus();
  export const select = () => input.select();
</script>

<div class="password">
  <input bind:this={input} bind:value class="input" type={shown ? 'text' : 'password'} {placeholder}
         autocomplete="new-password" onkeydown={(ev) => ev.key === 'Enter' && onenter?.()} />
  <button class="password__reveal" type="button" tabindex="-1" onclick={() => (shown = !shown)}
          title={shown ? T.hide : T.show}>
    <Icon name={shown ? 'eye-off' : 'eye'} />
  </button>
</div>
