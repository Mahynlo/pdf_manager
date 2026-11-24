<!-- Cabecera de herramienta: su icono en una píldora de su color, título y subtítulo. -->
<script lang="ts">
  import Icon from '../Icon.svelte';

  let { icon, color, title, subtitle }: { icon: string; color: string; title: string; subtitle: string } = $props();
</script>

<header class="tool-header">
  <span class="tool-header__icon" style:--c={color} aria-hidden="true"><Icon name={icon} size={24} /></span>
  <div>
    <h1 class="title">{title}</h1>
    <p class="muted">{subtitle}</p>
  </div>
</header>
