<!-- Campo de contraseña con botón para mostrarla (PasswordLineEdit en Qt). -->
<script>
  import Icon from '../Icon.svelte';

  let { value = $bindable(''), placeholder = '', onenter } = $props();
  let input;
  let shown = $state(false);

  export const focus = () => input.focus();
  export const select = () => input.select();
</script>

<div class="password">
  <input bind:this={input} bind:value class="input" type={shown ? 'text' : 'password'} {placeholder}
         autocomplete="new-password" onkeydown={(ev) => ev.key === 'Enter' && onenter?.()} />
  <button class="password__reveal" type="button" tabindex="-1" onclick={() => (shown = !shown)}
          title={shown ? 'Ocultar contraseña' : 'Mostrar contraseña'}>
    <Icon name={shown ? 'eye-off' : 'eye'} />
  </button>
</div>
