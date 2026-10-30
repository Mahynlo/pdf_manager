<!--
  Páginas del visor dibujadas por EmbedPDF dentro del lienzo (`canvas.el`, que es el
  contenedor con scroll). canvas.js lo monta cuando el registro de la app está listo
  (los hooks de EmbedPDF lo leen al crearse). Solo se montan las páginas a la vista: el
  Scroller las crea y las quita al desplazarse. Cada página es un PdfPage.svelte.
-->
<script>
  import { setContext } from 'svelte';
  import { useDocumentState } from '@embedpdf/core/svelte';
  import { Scroller } from '@embedpdf/plugin-scroll/svelte';
  import { useIsViewportGated, useViewportRef } from '@embedpdf/plugin-viewport/svelte';
  import { ZoomGestureWrapper } from '@embedpdf/plugin-zoom/svelte';
  import PdfPage from './PdfPage.svelte';

  const BASE_SCALE = 1; // px por punto de la imagen de fondo (sin contar la densidad de pantalla)

  let { element, overlay } = $props();
  let documentId = $state(null);

  /** Pone a la vista el documento `id` del registro (canvas.js, cuando ya está cargado). */
  export function show(id) {
    documentId = id;
  }

  const viewport = useViewportRef(() => documentId);
  viewport.containerRef = element;
  setContext('viewport-element', { current: element }); // para el zoom con pellizco

  const gated = useIsViewportGated(() => documentId);
  const docState = useDocumentState(() => documentId);
  const baseScale = $derived(Math.min(docState.current?.scale ?? BASE_SCALE, BASE_SCALE));
</script>

{#if documentId && !gated.current}
  <!-- Ctrl+rueda lo lleva canvas.js: aquí cada paso de ratón duplicaría el zoom. -->
  <ZoomGestureWrapper {documentId} class="pdf-canvas__inner" enableWheel={false}>
    <Scroller {documentId}>
      {#snippet renderPage(page)}
        <PdfPage {documentId} pageIndex={page.pageIndex} {baseScale} {overlay} />
      {/snippet}
    </Scroller>
  </ZoomGestureWrapper>
{/if}
