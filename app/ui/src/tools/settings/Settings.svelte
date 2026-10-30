<!-- Herramienta Ajustes: apariencia, atajos de teclado y almacenamiento/diagnóstico. -->
<script>
  import { call } from '$lib/api.js';
  import SectionCard from '$lib/components/SectionCard.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import Icon from '$lib/Icon.svelte';
  import { theme } from '$lib/theme.svelte.js';
  import { openModal, toast } from '$lib/ui.js';
  import LogDialog from './LogDialog.svelte';
  import { SHORTCUTS } from './shortcuts.js';

  let { tool } = $props();

  const about = call('app.about');

  async function clearRecent() {
    await call('documents.clear_recent');
    toast('El historial de archivos recientes ha sido eliminado.', 'success');
  }

  async function showLog() {
    openModal(LogDialog, { text: await call('app.diagnostics_log') });
  }
</script>

{#snippet keys(combo)}
  {#each combo as key, i (i)}
    {#if i > 0}<span class="muted">+</span>{/if}<kbd class="keycap">{key}</kbd>
  {/each}
{/snippet}

<div class="tool-page">
  <ToolHeader emoji={tool.emoji} color={tool.color} title="Configuración General"
              subtitle="Administra las preferencias y la apariencia de la aplicación" />
  <hr class="divider" />
  <div class="settings">
    <SectionCard title="Apariencia">
      <div class="setting-row">
        <span class="panel-icon"><Icon name={theme.dark ? 'moon' : 'sun'} size={20} /></span>
        <div class="grow">
          <p class="label">Tema de la aplicación</p>
          <p class="muted">Cambia entre tema claro y oscuro para mayor comodidad visual</p>
        </div>
        <select class="input select theme-select" value={theme.dark ? 'dark' : 'light'}
                onchange={(ev) => theme.set(ev.currentTarget.value === 'dark')}>
          <option value="light">Claro</option>
          <option value="dark">Oscuro</option>
        </select>
      </div>
    </SectionCard>

    <SectionCard title="Atajos de teclado">
      {#each SHORTCUTS as [group, rows] (group)}
        <p class="caption shortcut-group">{group}</p>
        {#each rows as [desc, combos] (desc)}
          <div class="shortcut-row">
            <span class="grow">{desc}</span>
            <span class="shortcut-keys">
              {#each combos as combo, i (i)}
                {#if i > 0}<span class="muted">o</span>{/if}{@render keys(combo)}
              {/each}
            </span>
          </div>
        {/each}
      {/each}
    </SectionCard>

    <SectionCard title="Almacenamiento y Diagnóstico">
      <div class="setting-row">
        <span class="grow">Historial de archivos recientes:</span>
        <button class="btn" type="button" onclick={clearRecent}>Vaciar historial</button>
      </div>
      <div class="setting-row">
        <span class="muted grow">
          {#await about then v}
            Extraer PDFs v{v.app} · Motor PDF: PyMuPDF v{v.pymupdf} | Entorno: pywebview v{v.pywebview} (WebView2) · Python {v.python}
          {/await}
        </span>
        <button class="btn" type="button" onclick={showLog}><Icon name="file-text" />Ver Registro de Diagnóstico...</button>
      </div>
    </SectionCard>
  </div>
</div>
