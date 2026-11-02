<!-- Aviso dentro de la herramienta (StatusBanner en Qt). `message` vacío lo oculta. -->
<script lang="ts">
  import Icon from '../Icon.svelte';

  import type { Tone } from '../feedback.svelte.ts';

  let { message = '', tone = 'success' }: { message?: string; tone?: Tone } = $props();
</script>

<div class="banner banner--{tone}" role="status" hidden={!message}>
  <span class="banner__icon"><Icon name={tone === 'danger' ? 'circle-alert' : 'circle-check'} size={18} /></span>
  <span>{message}</span>
</div>
