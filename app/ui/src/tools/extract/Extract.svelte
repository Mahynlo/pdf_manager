<!--
  Herramienta Extraer: criterios a la izquierda; objetivos, acciones y resultados a la
  derecha. El trabajo corre en el backend (servicio "extract") y avisa con eventos extract:*.
-->
<script>
  import { onDestroy } from 'svelte';
  import { call, on } from '$lib/api.js';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import { fileName } from '$lib/dom.js';
  import Icon from '$lib/Icon.svelte';
  import { askPassword, confirmDialog, toast } from '$lib/ui.js';
  import Criteria from './Criteria.svelte';
  import Results from './Results.svelte';
  import Targets from './Targets.svelte';

  let { tool } = $props();

  let job = $state.raw(null);
  let running = $state(false);
  let cancelling = $state(false);
  let resultReady = $state(false);
  let progress = $state('');
  let summary = $state('Sin búsqueda ejecutada');
  let output = $state('single');
  let criteria = $state();
  let results = $state();

  const onState = (next) => (job = next);

  function setRunning(value) {
    running = value;
    cancelling = false;
  }

  async function start() {
    results.clear();
    try {
      job = await call('extract.start', { ...criteria.params(), split_by_doc: output === 'split' });
    } catch (err) {
      results.log(`✗ ${err.message}`, 'danger');
      return;
    }
    setRunning(true);
    resultReady = false;
    summary = 'Iniciando análisis…';
    progress = '';
  }

  async function cancel() {
    cancelling = true;
    progress = 'Cancelando...';
    await call('extract.cancel');
  }

  async function onPassword({ name }) {
    const unlocked = await askPassword(name, async (pwd) => {
      try {
        await call('extract.answer_password', pwd);
        return null;
      } catch (err) {
        return err.message;
      }
    });
    if (!unlocked) call('extract.answer_password', null); // omite el archivo
  }

  $effect(() => {
    const subscriptions = [
      on('extract:log', ({ text, tone }) => results?.log(text, tone)),
      on('extract:separator', () => results?.separator()),
      on('extract:progress', (text) => (progress = text)),
      on('extract:summary', (text) => (summary = text)),
      on('extract:match', (match) => results?.addMatch(match)),
      on('extract:password', onPassword),
      on('extract:finished', ({ path, count, files }) => {
        setRunning(false);
        if (!path) return;
        resultReady = true;
        summary = `Finalizado: ${count} coincidencia(s) en ${files} archivo(s). Salida: ${fileName(path)}`;
      }),
      on('extract:error', (message) => {
        setRunning(false);
        results?.log(`❌ Error: ${message}`, 'danger');
        toast(message, 'danger');
      }),
    ];
    return () => subscriptions.forEach((off) => off());
  });

  call('extract.state').then((s) => {
    job = s;
    setRunning(s.running);
  });

  export async function canClose() {
    return !running || confirmDialog('Extracción en curso', 'Hay una extracción en curso. ¿Cancelarla y cerrar la pestaña?');
  }

  onDestroy(() => call('extract.reset')); // cancela lo que siga en curso y vacía la lista
</script>

<div class="tool-page">
  <ToolHeader emoji={tool.emoji} color={tool.color} title="Extracción Inteligente de PDFs"
              subtitle="Escaneo semántico por palabras clave, OCR multicapa y similitud contextual de documentos" />
  {#if job}
    <div class="card extract">
      <section class="extract__criteria"><Criteria bind:this={criteria} {job} {onState} /></section>
      <div class="steps__sep"></div>
      <section class="extract__run">
        <Targets {job} {onState} bind:output />
        <div class="extract__actions">
          <button class="btn btn--primary btn--lg" type="button" disabled={running} onclick={start}>
            <Icon name="search" />Iniciar Búsqueda y Extracción
          </button>
          <button class="btn btn--lg" type="button" disabled={!running || cancelling} onclick={cancel}>
            <Icon name="circle-stop" />Cancelar
          </button>
          <button class="btn btn--lg" type="button" disabled={!resultReady} onclick={() => call('extract.open_result')}>
            <Icon name="eye" />Ver PDF Generado
          </button>
        </div>
        <p class="hint">{progress}</p>
        <p class="caption">{summary}</p>
        <Results bind:this={results} />
      </section>
    </div>
  {/if}
</div>
