<!-- Tarjeta de sección: título de acento, separador y contenido (Ajustes, Ayuda). -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let { title, children }: { title: string; children: Snippet } = $props();
</script>

<section class="card section-card">
  <h2 class="section-title">{title}</h2>
  <hr class="divider" />
  {@render children()}
</section>
