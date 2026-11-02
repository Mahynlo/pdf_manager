<!--
  Columna izquierda de Extraer: modo «Búsqueda inteligente» (pasos 1 y 2) o «Por rango
  numérico». `params()` da los parámetros del modo activo.
-->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.ts';
  import { askPassword } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { ExtractJob } from './types.ts';

  const T = t.extract;

  /** `job`: estado del servicio extract; `onState(job)` recibe el nuevo tras un cambio. */
  let { job, onState }: { job: ExtractJob; onState: (job: ExtractJob) => void } = $props();

  let mode = $state(0);
  let referencePages = $state('');
  let keywords = $state('');
  let matchMode = $state('all');
  let accents = $state(true);
  let caseSensitive = $state(false);
  let wholeWord = $state(false);
  let hints = $state('');
  let range = $state('');

  export function params(): Record<string, unknown> {
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
    const res = await call<{ state: ExtractJob; locked: boolean }>('extract.pick_reference');
    onState(res.state);
    if (!res.locked) return;
    await askPassword(res.state.reference!.name, async (pwd) => {
      try {
        onState(await call<ExtractJob>('extract.unlock_reference', pwd));
        return null;
      } catch (err) {
        return (err as Error).message;
      }
    });
  }

  async function presets(ev: MouseEvent & { currentTarget: HTMLButtonElement }) {
    const anchor = ev.currentTarget;
    const list = await call<{ label: string; keywords: string }[]>('extract.presets');
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
    <h3 class="section-title">{T.reference.title}</h3>
    <div class="row">
      <button class="btn grow" type="button" onclick={pickReference}><Icon name="folder-open" />{T.reference.open}</button>
      <button class="btn" type="button" onclick={async () => onState(await call<ExtractJob>('extract.clear_reference'))}>
        <Icon name="x" />{T.reference.remove}
      </button>
    </div>
    <div class="file-box file-box--stack">
      <p class="muted ellipsis" title={job.reference?.path ?? ''}>{T.reference.file(job.reference?.name ?? null)}</p>
      <p class="muted">{T.reference.kind(job.reference?.kind ?? null)}</p>
    </div>
    <input class="input" bind:value={referencePages} placeholder={T.reference.pages} />

    <hr class="divider" />
    <div class="row">
      <h3 class="section-title grow">{T.criteria.title}</h3>
      <button class="btn btn--ghost btn--sm" type="button" onclick={presets}><Icon name="zap" />{T.criteria.presets}</button>
    </div>
    <textarea class="input textarea" bind:value={keywords} placeholder={T.criteria.keywords}></textarea>
    <RadioGroup bind:value={matchMode} options={[
      { value: 'all', label: T.criteria.matchAll },
      { value: 'any', label: T.criteria.matchAny },
    ]} />
    <div class="radio-group">
      <Checkbox label={T.criteria.ignoreAccents} bind:checked={accents} />
      <Checkbox label={T.criteria.caseSensitive} bind:checked={caseSensitive} />
      <Checkbox label={T.criteria.wholeWord} bind:checked={wholeWord} />
    </div>
    <input class="input" bind:value={hints} placeholder={T.criteria.hints} />
  </div>
{/snippet}

{#snippet byRange()}
  <div class="panel-stack">
    <h3 class="section-title">{T.range.title}</h3>
    <p class="muted">{T.range.text}</p>
    <input class="input" bind:value={range} placeholder={T.range.placeholder} />
  </div>
{/snippet}

<SubTabs bind:current={mode} tabs={[
  { label: T.tabs.smart, icon: 'sparkles', panel: smart },
  { label: T.tabs.range, icon: 'hash', panel: byRange },
]} />
