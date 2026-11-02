<!--
  Una página del visor (la monta PdfPages.svelte con el Scroller de EmbedPDF):
  - la imagen de la página entera a baja resolución (RenderLayer), que se ve enseguida;
  - el mosaico a la resolución del zoom (TilingLayer), solo de la parte a la vista;
  - las anotaciones (AnnotationLayer de EmbedPDF): las dibuja, las selecciona, las mueve y
    redimensiona, edita el texto libre y crea las nuevas con su herramienta activa. Las marcas
    de censura pendientes son anotaciones: las dibuja con los dibujantes del complemento de
    censura, y RedactionLayer, el rectángulo o la selección mientras se marcan;
  - MarqueeSelection: el rectángulo arrastrando de la selección, que solo usa «Marcar» (censura)
    para marcar un área (en la selección de texto está apagado, ver embed.js);
  - las capas del visor (`overlay`): marcas de selección, búsqueda, OCR o censura. Son
    elementos que guarda canvas.js y aquí solo se enganchan a la página.

  La imagen, el mosaico y las anotaciones van dentro de:
  - Rotate, que gira con CSS la página según su /Rotate (EmbedPDF la dibuja sin girar);
  - el PagePointerProvider, que pasa el ratón de la página a los complementos de EmbedPDF
    (la selección de texto y las anotaciones). Los eventos siguen subiendo hasta el lienzo,
    donde escuchan las demás herramientas.
  Nuestras capas quedan fuera, encima, en la página tal como se ve (y sin recibir el
  ratón: ver viewer.css).

  Es un componente aparte para que el enganche de las capas dependa solo del número de
  página: el Scroller da objetos de página nuevos en cada cambio de su estado (al
  seleccionar, por ejemplo) y, leídos directamente, el enganche se repetía cada vez.
-->
<script>
  import { AnnotationLayer } from '@embedpdf/plugin-annotation/svelte';
  import { PagePointerProvider } from '@embedpdf/plugin-interaction-manager/svelte';
  import { RedactionLayer, redactRenderers } from '@embedpdf/plugin-redaction/svelte';
  import { MarqueeSelection } from '@embedpdf/plugin-selection/svelte';
  import { RenderLayer } from '@embedpdf/plugin-render/svelte';
  import { Rotate } from '@embedpdf/plugin-rotate/svelte';
  import { TilingLayer } from '@embedpdf/plugin-tiling/svelte';

  let { documentId, pageIndex, baseScale, overlay } = $props();
  const index = $derived(pageIndex); // solo cambia si cambia el número
  // Marco y tiradores de la anotación seleccionada con el color de acento de la app.
  const OUTLINE = { color: 'var(--accent)', width: 1.5, offset: 2 };
  const HANDLES = { size: 10, color: 'var(--accent)' };
</script>

<div class="pdf-page">
  <span class="pdf-page__label">Página {index + 1}</span>
  <Rotate {documentId} pageIndex={index} class="pdf-page__rotate">
    <PagePointerProvider {documentId} pageIndex={index} class="pdf-page__pointer">
      <RenderLayer {documentId} pageIndex={index} scale={baseScale} class="pdf-page__img" draggable="false" />
      <TilingLayer {documentId} pageIndex={index} class="pdf-page__tiles" />
      <AnnotationLayer {documentId} pageIndex={index} selectionOutline={OUTLINE} resizeUI={HANDLES} vertexUI={HANDLES}
                       annotationRenderers={redactRenderers} />
      <RedactionLayer {documentId} pageIndex={index} />
      <MarqueeSelection {documentId} pageIndex={index} />
    </PagePointerProvider>
  </Rotate>
  <div class="pdf-page__hook" {@attach overlay(index)}></div>
</div>
