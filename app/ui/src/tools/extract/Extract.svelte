<!--
  Herramienta Extraer: criterios a la izquierda; objetivos, acciones y resultados a la
  derecha. El trabajo corre en el backend (servicio "extract") y avisa con eventos extract:*.
-->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { call, on } from '$lib/api.ts';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import { fileName } from '$lib/dom.ts';
  import Icon from '$lib/Icon.svelte';
  import { askPassword, confirmDialog, toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import type { Tool } from '../../shell/tools.ts';
  import Criteria from './Criteria.svelte';
  import Results from './Results.svelte';
  import Targets from './Targets.svelte';
  import type { ExtractJob, ExtractMatch, LogTone } from './types.ts';

  const T = t.extract;

  let { tool }: { tool: Tool } = $props();

  let job = $state.raw<ExtractJob | null>(null);
  let running = $state(false);
  let cancelling = $state(false);
  let resultReady = $state(false);
  let progress = $state('');
  let summary = $state(T.run.idle);
  let output = $state('single');
  let criteria = $state<Criteria>();
  let results = $state<Results>();

  const onState = (next: ExtractJob) => (job = next);

  function setRunning(value: boolean) {
    running = value;
    cancelling = false;
  }

  async function start() {
    results!.clear();
    try {
      job = await call<ExtractJob>('extract.start', { ...criteria!.params(), split_by_doc: output === 'split' });
    } catch (err) {
      results!.log(T.run.startError((err as Error).message), 'danger');
      return;
    }
    setRunning(true);
    resultReady = false;
    summary = T.run.starting;
    progress = '';
  }

  async function cancel() {
    cancelling = true;
    progress = T.run.cancelling;
    await call('extract.cancel');
  }

  async function onPassword({ name }: { name: string }) {
    const unlocked = await askPassword(name, async (pwd) => {
      try {
        await call('extract.answer_password', pwd);
        return null;
      } catch (err) {
        return (err as Error).message;
      }
    });
    if (!unlocked) call('extract.answer_password', null); // omite el archivo
  }

  $effect(() => {
    const subscriptions = [
      on<{ text: string; tone: LogTone }>('extract:log', ({ text, tone }) => results?.log(text, tone)),
      on('extract:separator', () => results?.separator()),
      on<string>('extract:progress', (text) => (progress = text)),
      on<string>('extract:summary', (text) => (summary = text)),
      on<ExtractMatch>('extract:match', (match) => results?.addMatch(match)),
      on('extract:password', onPassword),
      on<{ path: string | null; count: number; files: number }>('extract:finished', ({ path, count, files }) => {
        setRunning(false);
        if (!path) return;
        resultReady = true;
        summary = T.run.finished(count, files, fileName(path));
      }),
      on<string>('extract:error', (message) => {
        setRunning(false);
        results?.log(T.run.error(message), 'danger');
        toast(message, 'danger');
      }),
    ];
    return () => subscriptions.forEach((off) => off());
  });

  call<ExtractJob>('extract.state').then((s) => {
    job = s;
    setRunning(s.running);
  });

  export async function canClose() {
    return !running || confirmDialog(T.run.closeTitle, T.run.closeQuestion);
  }

  onDestroy(() => call('extract.reset')); // cancela lo que siga en curso y vacía la lista
</script>

<div class="tool-page">
  <ToolHeader emoji={tool.emoji} color={tool.color} title={T.title} subtitle={T.subtitle} />
  {#if job}
    <div class="card extract">
      <section class="extract__criteria"><Criteria bind:this={criteria} {job} {onState} /></section>
      <div class="steps__sep"></div>
      <section class="extract__run">
        <Targets {job} {onState} bind:output />
        <div class="extract__actions">
          <button class="btn btn--primary btn--lg" type="button" disabled={running} onclick={start}>
            <Icon name="search" />{T.run.start}
          </button>
          <button class="btn btn--lg" type="button" disabled={!running || cancelling} onclick={cancel}>
            <Icon name="circle-stop" />{T.run.cancel}
          </button>
          <button class="btn btn--lg" type="button" disabled={!resultReady} onclick={() => call('extract.open_result')}>
            <Icon name="eye" />{T.run.open}
          </button>
        </div>
        <p class="hint">{progress}</p>
        <p class="caption">{summary}</p>
        <Results bind:this={results} />
      </section>
    </div>
  {/if}
</div>
