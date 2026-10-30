<!-- Cabecera de herramienta: emoji en una píldora del color de la herramienta, título y subtítulo. -->
<script>
  let { emoji, color, title, subtitle } = $props();
</script>

<header class="tool-header">
  <span class="tool-header__icon" style:--c={color} aria-hidden="true">{emoji}</span>
  <div>
    <h1 class="title">{title}</h1>
    <p class="muted">{subtitle}</p>
  </div>
</header>
