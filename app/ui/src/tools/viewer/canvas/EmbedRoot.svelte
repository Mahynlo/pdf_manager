<!--
  Raíz <EmbedPDF> de la app (una sola, ver registry() en embed.js). No dibuja nada: cada
  visor monta sus páginas (PdfPages.svelte) aparte, sobre este registro. Avisa con
  `onReady` cuando el registro ya está publicado para los componentes y con sus
  complementos listos.
-->
<script>
  import { EmbedPDF, useRegistry } from '@embedpdf/core/svelte';

  let { engine, plugins, onReady } = $props();
  const context = useRegistry();

  $effect(() => {
    if (context.registry && context.pluginsReady) onReady(context.registry);
  });
</script>

<EmbedPDF {engine} {plugins}>
  {#snippet children()}{/snippet}
</EmbedPDF>
