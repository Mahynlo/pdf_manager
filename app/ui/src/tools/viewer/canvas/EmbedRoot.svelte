<!--
  Raíz <EmbedPDF> de la app (una sola, ver registry() en embed.ts). No dibuja nada: cada
  visor monta sus páginas (PdfPages.svelte) aparte, sobre este registro. Avisa con
  `onReady` cuando el registro ya está publicado para los componentes y con sus
  complementos listos.
-->
<script lang="ts">
  import type { PluginBatchRegistrations, PluginRegistry } from '@embedpdf/core';
  import { EmbedPDF, useRegistry } from '@embedpdf/core/svelte';
  import type { PdfEngine } from '@embedpdf/models';

  let { engine, plugins, onReady }: {
    engine: PdfEngine;
    plugins: PluginBatchRegistrations;
    onReady: (registry: PluginRegistry) => void;
  } = $props();
  const context = useRegistry();

  $effect(() => {
    if (context.registry && context.pluginsReady) onReady(context.registry);
  });
</script>

<EmbedPDF {engine} {plugins}>
  {#snippet children()}{/snippet}
</EmbedPDF>
