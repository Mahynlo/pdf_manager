<!-- Campo de contraseña con botón para mostrarla (PasswordLineEdit en Qt). Sin corrector ni
     autocompletar: al mostrarla es un campo de texto, y el corrector (en algunos navegadores, en
     la nube) la leería. -->
<script lang="ts">
  import Icon from '../Icon.svelte';
  import { t } from '$texts';

  const T = t.common.password;

  let { value = $bindable(''), placeholder = '', invalid = false, onenter }: {
    value?: string;
    placeholder?: string;
    invalid?: boolean; // marca el campo en rojo (y lo anuncia a los lectores de pantalla)
    onenter?: () => void;
  } = $props();
  let input: HTMLInputElement;
  let shown = $state(false);

  export const focus = () => input.focus();
  export const select = () => input.select();
</script>

<div class="password">
  <input bind:this={input} bind:value class="input" class:is-invalid={invalid} type={shown ? 'text' : 'password'} {placeholder}
         autocomplete="new-password" spellcheck="false" autocapitalize="off" autocorrect="off" aria-invalid={invalid}
         onkeydown={(ev) => ev.key === 'Enter' && onenter?.()} />
  <button class="password__reveal" type="button" tabindex="-1" onclick={() => (shown = !shown)}
          title={shown ? T.hide : T.show}>
    <Icon name={shown ? 'eye-off' : 'eye'} />
  </button>
</div>
