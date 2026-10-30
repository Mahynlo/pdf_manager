<!-- Recuadro con el archivo elegido; sin `text` muestra «No hay PDF seleccionado». -->
<script>
  import Icon from '$lib/Icon.svelte';

  let { text = '', tone = null } = $props();
</script>

<div class="file-box">
  <Icon name="file-text" size={18} />
  <span class="file-box__name ellipsis {tone ? `tone-${tone}` : 'muted'}">{text || 'No hay PDF seleccionado'}</span>
</div>
