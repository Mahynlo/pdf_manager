<!-- Dos columnas «Paso 1 | Paso 2» separadas por una línea vertical (las dos pestañas de Seguridad). -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let { leftTitle, rightTitle, left, right }: {
    leftTitle: string;
    rightTitle: string;
    left: Snippet;
    right: Snippet;
  } = $props();
</script>

<div class="steps">
  <div class="steps__col steps__col--left">
    <h2 class="step-title">{leftTitle}</h2>
    {@render left()}
  </div>
  <div class="steps__sep"></div>
  <div class="steps__col">
    <h2 class="step-title">{rightTitle}</h2>
    {@render right()}
  </div>
</div>
