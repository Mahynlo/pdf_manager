<!--
  Icono vectorial del mismo juego que el resto de la app (icons.json, el de Qt).
  Usa stroke="currentColor": toma el color del texto y sigue el tema.
    <Icon name="save" />  <Icon name="plus" size={18} />
-->
<script>
  import { paths } from './icons.js';

  let { name, size = 16 } = $props();

  $effect(() => {
    if (!(name in paths)) console.warn(`Icono desconocido: ${name}`);
  });
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  {@html paths[name] ?? ''}
</svg>
