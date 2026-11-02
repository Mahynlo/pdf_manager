<!-- Recuadro con el archivo elegido; sin `text` muestra «No hay PDF seleccionado». -->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import type { Tone } from '$lib/ui.ts';
  import { t } from '$texts';

  let { text = '', tone = null }: { text?: string | null; tone?: Tone | null } = $props();
</script>

<div class="file-box">
  <Icon name="file-text" size={18} />
  <span class="file-box__name ellipsis {tone ? `tone-${tone}` : 'muted'}">{text || t.security.noFile}</span>
</div>
