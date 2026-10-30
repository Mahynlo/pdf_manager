<!-- Herramienta Ayuda: información general y manuales en Markdown (el backend los da ya en HTML seguro). -->
<script>
  import { call } from '$lib/api.js';
  import SectionCard from '$lib/components/SectionCard.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.js';
  import { FAQ, GETTING_STARTED, TOOLS_HELP } from './content.js';

  let { tool } = $props();

  let docs = $state(null);
  let active = $state(null);
  let doc = $state({ title: 'Selecciona un documento', html: '' });
  let body;

  async function open(item) {
    active = item.file;
    try {
      doc = await call('help.document', item.file);
      body.scrollTop = 0;
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  call('help.documents').then((list) => {
    docs = list;
    if (list.length) open(list[0]);
  });

  // Los enlaces de los manuales se abren en el navegador, no dentro de la app.
  function onclick(ev) {
    const link = ev.target.closest('a[href]');
    if (!link) return;
    ev.preventDefault();
    call('app.open_url', link.href);
  }
</script>

{#snippet infoRows(rows)}
  {#each rows as [emoji, title, text] (title)}
    <div class="info-row">
      <span class="info-row__icon" aria-hidden="true">{emoji}</span>
      <div><p class="label">{title}</p><p class="muted">{text}</p></div>
    </div>
  {/each}
{/snippet}

{#snippet info()}
  <div class="settings help-info">
    <SectionCard title="Primeros pasos">{@render infoRows(GETTING_STARTED)}</SectionCard>
    <SectionCard title="Herramientas disponibles">{@render infoRows(TOOLS_HELP)}</SectionCard>
    <SectionCard title="Preguntas frecuentes">
      {#each FAQ as [question, answer] (question)}
        <div class="faq-row"><p class="label">Q: {question}</p><p class="muted">{answer}</p></div>
      {/each}
    </SectionCard>
  </div>
{/snippet}

{#snippet manuals()}
  <div class="help-docs">
    <aside class="card help-docs__list">
      <h2 class="step-title">Documentos</h2>
      <hr class="divider" />
      <div class="doc-list">
        {#if docs && !docs.length}
          <p class="muted">No hay documentos de ayuda.</p>
        {/if}
        {#each docs ?? [] as item (item.file)}
          <button class="doc-list__item" class:is-active={active === item.file} type="button" onclick={() => open(item)}>
            <Icon name="book-open" /><span class="ellipsis">{item.title}</span>
          </button>
        {/each}
      </div>
    </aside>
    <section class="card help-docs__view">
      <h2 class="step-title">{doc.title}</h2>
      <hr class="divider" />
      <!-- HTML generado por el backend sin HTML crudo (seguro) -->
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
      <article class="markdown" bind:this={body} {onclick}>{@html doc.html}</article>
    </section>
  </div>
{/snippet}

<div class="tool-page tool-page--fill">
  <ToolHeader emoji={tool.emoji} color={tool.color} title="Ayuda y Guía de Uso"
              subtitle="Todo lo que necesitas saber para usar Extraer PDFs" />
  <hr class="divider" />
  <SubTabs tabs={[
    { label: 'Información general', icon: 'info', panel: info },
    { label: 'Documentación y manuales', icon: 'book-open', panel: manuals },
  ]} />
</div>
