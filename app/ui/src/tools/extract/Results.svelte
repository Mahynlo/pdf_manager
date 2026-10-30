<!-- Resultados de Extraer: registro de operación y tabla de coincidencias. -->
<script>
  import { tick } from 'svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';

  const SEPARATOR = '─'.repeat(45);
  const COLUMNS = ['Documento', 'Pág.', 'Puntuación', 'Términos Coincidentes', 'Modo'];

  let lines = $state([]); // [{ text, tone }]
  let matches = $state([]);
  let logEl;

  export function clear() {
    lines = [];
    matches = [];
  }

  export async function log(text, tone) {
    const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 24;
    lines.push({ text, tone });
    await tick();
    if (atBottom) logEl.scrollTop = logEl.scrollHeight; // sigue el final salvo que el usuario haya subido
  }

  export const separator = () => log(SEPARATOR, 'muted');

  export function addMatch(match) {
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
      <thead><tr>{#each COLUMNS as c (c)}<th>{c}</th>{/each}</tr></thead>
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
  { label: 'Registro de operación', icon: 'terminal', panel: logPanel },
  { label: `Tabla de coincidencias (${matches.length})`, icon: 'table', panel: table },
]} />
