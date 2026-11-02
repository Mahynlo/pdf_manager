<!-- Resultados de Extraer: registro de operación y tabla de coincidencias. -->
<script lang="ts">
  import { tick } from 'svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import { t } from '$texts';
  import type { ExtractMatch, LogTone } from './types.ts';

  const T = t.extract.results;
  const SEPARATOR = '─'.repeat(45);

  let lines = $state<{ text: string; tone: LogTone }[]>([]);
  let matches = $state<ExtractMatch[]>([]);
  let logEl: HTMLDivElement;

  export function clear() {
    lines = [];
    matches = [];
  }

  export async function log(text: string, tone: LogTone = null) {
    const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 24;
    lines.push({ text, tone });
    await tick();
    if (atBottom) logEl.scrollTop = logEl.scrollHeight; // sigue el final salvo que el usuario haya subido
  }

  export const separator = () => log(SEPARATOR, 'muted');

  export function addMatch(match: ExtractMatch) {
    matches.push(match);
  }
</script>

{#snippet logPanel()}
  <div class="log" role="log" bind:this={logEl}>
    {#each lines as line, i (i)}
      <div class="log__line {line.tone ? `tone-${line.tone}` : ''}">{line.text}</div>
    {/each}
  </div>
{/snippet}

{#snippet table()}
  <div class="table-wrap">
    <table class="table">
      <thead><tr>{#each T.columns as c (c)}<th>{c}</th>{/each}</tr></thead>
      <tbody>
        {#each matches as m, i (i)}
          <tr>
            <td title={m.name}>{m.name}</td><td>{m.page}</td><td>{m.score.toFixed(2)}</td><td>{m.terms}</td><td>{m.mode}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/snippet}

<SubTabs tabs={[
  { label: T.log, icon: 'terminal', panel: logPanel },
  { label: T.table(matches.length), icon: 'table', panel: table },
]} />
