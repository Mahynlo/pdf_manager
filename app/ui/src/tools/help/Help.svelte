<!-- Herramienta Ayuda: información general y manuales en Markdown (el backend los da ya en HTML seguro). -->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import SectionCard from '$lib/components/SectionCard.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import Icon from '$lib/Icon.svelte';
  import { toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { Tool } from '../../shell/tools.ts';

  /** Manual de `help.documents`. */
  interface HelpDoc {
    file: string;
    title: string;
  }

  const T = t.help;

  let { tool }: { tool: Tool } = $props();

  let docs = $state<HelpDoc[] | null>(null);
  let active = $state<string | null>(null);
  let doc = $state({ title: T.manuals.noSelection, html: '' });
  let body: HTMLElement;

  async function open(item: HelpDoc) {
    active = item.file;
    try {
      doc = await call<{ title: string; html: string }>('help.document', item.file);
      body.scrollTop = 0;
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  call<HelpDoc[]>('help.documents').then((list) => {
    docs = list;
    if (list.length) open(list[0]);
  });

  // Los enlaces de los manuales se abren en el navegador, no dentro de la app.
  function onclick(ev: MouseEvent) {
    const link = (ev.target as Element).closest<HTMLAnchorElement>('a[href]');
    if (!link) return;
    ev.preventDefault();
    call('app.open_url', link.href);
  }
</script>

{#snippet infoRows(rows: [string, string, string][])}
  {#each rows as [emoji, title, text] (title)}
    <div class="info-row">
      <span class="info-row__icon" aria-hidden="true">{emoji}</span>
      <div><p class="label">{title}</p><p class="muted">{text}</p></div>
    </div>
  {/each}
{/snippet}

{#snippet info()}
  <div class="settings help-info">
    <SectionCard title={T.info.gettingStarted}>{@render infoRows(T.gettingStarted)}</SectionCard>
    <SectionCard title={T.info.tools}>{@render infoRows(T.toolsHelp)}</SectionCard>
    <SectionCard title={T.info.faq}>
      {#each T.faq as [question, answer] (question)}
        <div class="faq-row"><p class="label">{T.info.question(question)}</p><p class="muted">{answer}</p></div>
      {/each}
    </SectionCard>
  </div>
{/snippet}

{#snippet manuals()}
  <div class="help-docs">
    <aside class="card help-docs__list">
      <h2 class="step-title">{T.manuals.title}</h2>
      <hr class="divider" />
      <div class="doc-list">
        {#if docs && !docs.length}
          <p class="muted">{T.manuals.empty}</p>
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
  <ToolHeader emoji={tool.emoji} color={tool.color} title={T.title} subtitle={T.subtitle} />
  <hr class="divider" />
  <SubTabs tabs={[
    { label: T.tabs.info, icon: 'info', panel: info },
    { label: T.tabs.manuals, icon: 'book-open', panel: manuals },
  ]} />
</div>
