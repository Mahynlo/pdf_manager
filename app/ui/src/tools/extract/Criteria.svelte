<!--
  Columna izquierda de Extraer: modo «Búsqueda inteligente» (pasos 1 y 2) o «Por rango
  numérico». `params()` da los parámetros del modo activo.
-->
<script>
  import { call } from '$lib/api.js';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.js';
  import { askPassword } from '$lib/ui.js';

  /** `job`: estado del servicio extract; `onState(job)` recibe el nuevo tras un cambio. */
  let { job, onState } = $props();

  let mode = $state(0);
  let referencePages = $state('');
  let keywords = $state('');
  let matchMode = $state('all');
  let accents = $state(true);
  let caseSensitive = $state(false);
  let wholeWord = $state(false);
  let hints = $state('');
  let range = $state('');

  export function params() {
    if (mode === 1) return { mode: 'range', range };
    return {
      mode: 'smart',
      reference_pages: referencePages,
      keywords,
      match_all: matchMode === 'all',
      ignore_accents: accents,
      case_sensitive: caseSensitive,
      whole_word: wholeWord,
      hint_pages: hints,
    };
  }

  async function pickReference() {
    const res = await call('extract.pick_reference');
    onState(res.state);
    if (!res.locked) return;
    await askPassword(res.state.reference.name, async (pwd) => {
      try {
        onState(await call('extract.unlock_reference', pwd));
        return null;
      } catch (err) {
        return err.message;
      }
    });
  }

  async function presets(ev) {
    const anchor = ev.currentTarget;
    const list = await call('extract.presets');
    openMenu(anchor, list.map((p) => ({
      label: p.label,
      onSelect: () => {
        const current = keywords.trim();
        keywords = current ? `${current}\n${p.keywords}` : p.keywords;
      },
    })));
  }
</script>

{#snippet smart()}
  <div class="panel-stack">
    <h3 class="section-title">Paso 1: Documento de Referencia (Opcional)</h3>
    <div class="row">
      <button class="btn grow" type="button" onclick={pickReference}><Icon name="folder-open" />Abrir PDF Referencia</button>
      <button class="btn" type="button" onclick={async () => onState(await call('extract.clear_reference'))}>
        <Icon name="x" />Quitar
      </button>
    </div>
    <div class="file-box file-box--stack">
      <p class="muted ellipsis" title={job.reference?.path ?? ''}>Referencia: {job.reference ? job.reference.name : 'sin archivo'}</p>
      <p class="muted">Tipo: {job.reference ? job.reference.kind : '-'}</p>
    </div>
    <input class="input" bind:value={referencePages} placeholder="Páginas de referencia (ej: 1,3-5) — Vacío = todas" />

    <hr class="divider" />
    <div class="row">
      <h3 class="section-title grow">Paso 2: Patrón de Búsqueda y Criterios</h3>
      <button class="btn btn--ghost btn--sm" type="button" onclick={presets}><Icon name="zap" />Preajustes</button>
    </div>
    <textarea class="input textarea" bind:value={keywords}
              placeholder="Palabras clave / títulos / nombres (una por línea o separadas por coma)..."></textarea>
    <RadioGroup bind:value={matchMode} options={[
      { value: 'all', label: 'Todas las palabras (AND)' },
      { value: 'any', label: 'Cualquier palabra (OR)' },
    ]} />
    <div class="radio-group">
      <Checkbox label="Ignorar tildes (á=a)" bind:checked={accents} />
      <Checkbox label="Distinguir Mayús." bind:checked={caseSensitive} />
      <Checkbox label="Palabras completas" bind:checked={wholeWord} />
    </div>
    <input class="input" bind:value={hints} placeholder="Páginas sugeridas en objetivos (ej: 1,2) — Vacío = todas" />
  </div>
{/snippet}

{#snippet byRange()}
  <div class="panel-stack">
    <h3 class="section-title">Extracción Directa por Rango Numérico</h3>
    <p class="muted">
      Extrae rápida y directamente páginas específicas de los documentos objetivo seleccionados, sin análisis de texto:
    </p>
    <input class="input" bind:value={range} placeholder="Ejemplo: 1-3, 5, 8-10, 15" />
  </div>
{/snippet}

<SubTabs bind:current={mode} tabs={[
  { label: 'Búsqueda inteligente', icon: 'sparkles', panel: smart },
  { label: 'Por rango numérico', icon: 'hash', panel: byRange },
]} />
