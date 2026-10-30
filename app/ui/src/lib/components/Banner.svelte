<!-- Aviso dentro de la herramienta (StatusBanner en Qt). `message` vacío lo oculta. -->
<script>
  import Icon from '../Icon.svelte';

  let { message = '', tone = 'success' } = $props();
</script>

<div class="banner banner--{tone}" role="status" hidden={!message}>
  <span class="banner__icon"><Icon name={tone === 'danger' ? 'circle-alert' : 'circle-check'} size={18} /></span>
  <span>{message}</span>
</div>
