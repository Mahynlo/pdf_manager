<!-- Tarjeta de sección: título de acento, separador y contenido (Ajustes, Ayuda). -->
<script>
  let { title, children } = $props();
</script>

<section class="card section-card">
  <h2 class="section-title">{title}</h2>
  <hr class="divider" />
  {@render children()}
</section>
