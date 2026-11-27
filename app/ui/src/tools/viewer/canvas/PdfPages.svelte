<!--
  Páginas del visor dibujadas por EmbedPDF dentro del lienzo (`canvas.el`, que es el
  contenedor con scroll). canvas.ts lo monta cuando el registro de la app está listo
  (los hooks de EmbedPDF lo leen al crearse). Solo se montan las páginas a la vista: el
  Scroller las crea y las quita al desplazarse. Cada página es un PdfPage.svelte.

  Los dibujantes de los campos de formulario (los de plugin-form) llegan a la capa de anotaciones
  por un contexto de Svelte que, en EmbedPDF, da su raíz <EmbedPDF>. Las páginas se montan fuera de
  ella (embed.ts), así que el contexto lo da este componente, y la utilidad del complemento que los
  apunta en él (la que <EmbedPDF> montaría sola) se monta aquí.
-->
<script lang="ts">
  import { setContext } from 'svelte';
  import type { Attachment } from 'svelte/attachments';
  import { useDocumentState } from '@embedpdf/core/svelte';
  import { provideRendererRegistry } from '@embedpdf/plugin-annotation/svelte';
  import { FormPluginPackage } from '@embedpdf/plugin-form/svelte';
  import { Scroller } from '@embedpdf/plugin-scroll/svelte';
  import { useIsViewportGated, useViewportRef } from '@embedpdf/plugin-viewport/svelte';
  import { ZoomGestureWrapper } from '@embedpdf/plugin-zoom/svelte';
  import PdfPage from './PdfPage.svelte';

  const BASE_SCALE = 1; // px por punto de la imagen de fondo (sin contar la densidad de pantalla)
  const FORM_UTILITIES = FormPluginPackage.autoMountElements().filter((e) => e.type === 'utility').map((e) => e.component);
  provideRendererRegistry();

  /** `element`: el contenedor con scroll del lienzo; `overlay(i)`: engancha la capa del visor de la página `i`. */
  let { element, overlay }: { element: HTMLDivElement; overlay: (index: number) => Attachment<HTMLElement> } = $props();
  let documentId = $state<string | null>(null);

  /** Pone a la vista el documento `id` del registro (canvas.ts, cuando ya está cargado). */
  export function show(id: string) {
    documentId = id;
  }

  // `element` (el contenedor con scroll del lienzo) no cambia mientras existe el componente.
  const viewport = useViewportRef(() => documentId);
  // svelte-ignore state_referenced_locally
  viewport.containerRef = element;
  // svelte-ignore state_referenced_locally
  setContext('viewport-element', { current: element }); // para el zoom con pellizco

  const gated = useIsViewportGated(() => documentId);
  const docState = useDocumentState(() => documentId);
  const baseScale = $derived(Math.min(docState.current?.scale ?? BASE_SCALE, BASE_SCALE));
</script>

{#each FORM_UTILITIES as Utility, i (i)}<Utility />{/each}

{#if documentId && !gated.current}
  <!-- Ctrl+rueda lo lleva canvas.ts: aquí cada paso de ratón duplicaría el zoom. -->
  <ZoomGestureWrapper {documentId} class="pdf-canvas__inner" enableWheel={false}>
    <Scroller {documentId}>
      {#snippet renderPage(page)}
        <!-- Cuando cambia lo que hay en esa posición (al mover, insertar o borrar páginas sube su
             versión), la página se monta de nuevo: sus capas de EmbedPDF no vuelven a pedir las
             imágenes de las anotaciones si solo cambia el contenido. -->
        {#key docState.current?.pageRefreshVersions?.[page.pageIndex] ?? 0}
          <PdfPage documentId={documentId!} pageIndex={page.pageIndex} {baseScale} {overlay} />
        {/key}
      {/snippet}
    </Scroller>
  </ZoomGestureWrapper>
{/if}
