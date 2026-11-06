<!-- Herramienta Ajustes: apariencia, atajos de teclado y almacenamiento/diagnóstico. -->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import SectionCard from '$lib/components/SectionCard.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import Icon from '$lib/Icon.svelte';
  import { theme } from '$lib/theme.svelte.ts';
  import { openModal, toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { Tool } from '../../shell/tools.ts';
  import LogDialog from './LogDialog.svelte';

  /** `app.about`. */
  interface About {
    app: string;
    pdfium: string;
    pywebview: string;
    python: string;
  }

  const T = t.settings;

  let { tool }: { tool: Tool } = $props();

  const about = call<About>('app.about');

  async function clearRecent() {
    await call('documents.clear_recent');
    toast(T.storage.recentCleared, 'success');
  }

  async function showLog() {
    openModal(LogDialog, { text: await call<string>('app.diagnostics_log') });
  }
</script>

{#snippet keys(combo: string[])}
  {#each combo as key, i (i)}
    {#if i > 0}<span class="muted">+</span>{/if}<kbd class="keycap">{key}</kbd>
  {/each}
{/snippet}

<div class="tool-page">
  <ToolHeader emoji={tool.emoji} color={tool.color} title={T.title} subtitle={T.subtitle} />
  <hr class="divider" />
  <div class="settings">
    <SectionCard title={T.appearance.title}>
      <div class="setting-row">
        <span class="panel-icon"><Icon name={theme.dark ? 'moon' : 'sun'} size={20} /></span>
        <div class="grow">
          <p class="label">{T.appearance.theme}</p>
          <p class="muted">{T.appearance.themeHint}</p>
        </div>
        <select class="input select theme-select" value={theme.dark ? 'dark' : 'light'}
                onchange={(ev) => theme.set(ev.currentTarget.value === 'dark')}>
          <option value="light">{T.appearance.light}</option>
          <option value="dark">{T.appearance.dark}</option>
        </select>
      </div>
    </SectionCard>

    <SectionCard title={T.shortcuts.title}>
      {#each T.shortcuts.groups as [group, rows] (group)}
        <p class="caption shortcut-group">{group}</p>
        {#each rows as [desc, combos] (desc)}
          <div class="shortcut-row">
            <span class="grow">{desc}</span>
            <span class="shortcut-keys">
              {#each combos as combo, i (i)}
                {#if i > 0}<span class="muted">{T.shortcuts.or}</span>{/if}{@render keys(combo)}
              {/each}
            </span>
          </div>
        {/each}
      {/each}
    </SectionCard>

    <SectionCard title={T.storage.title}>
      <div class="setting-row">
        <span class="grow">{T.storage.recent}</span>
        <button class="btn" type="button" onclick={clearRecent}>{T.storage.clearRecent}</button>
      </div>
      <div class="setting-row">
        <span class="muted grow">
          {#await about then v}
            {T.storage.about(v)}
          {/await}
        </span>
        <button class="btn" type="button" onclick={showLog}><Icon name="file-text" />{T.storage.showLog}</button>
      </div>
    </SectionCard>
  </div>
</div>
