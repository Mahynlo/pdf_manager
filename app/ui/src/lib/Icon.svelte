<!--
  Icono vectorial del mismo juego que el resto de la app (icons.json).
  Usa stroke="currentColor": toma el color del texto y sigue el tema.
    <Icon name="save" />  <Icon name="plus" size={18} />
-->
<script lang="ts">
  import { paths } from './icons.ts';

  let { name, size = 16 }: { name: string; size?: number } = $props();

  $effect(() => {
    if (!(name in paths)) console.warn(`Icono desconocido: ${name}`);
  });
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  {@html paths[name] ?? ''}
</svg>
