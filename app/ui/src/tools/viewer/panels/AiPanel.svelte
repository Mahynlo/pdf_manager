<!--
  Pestaña «IA» del panel lateral (ai_dock.py en Qt): chat sobre el documento y acciones
  rápidas (resumen, datos clave, datos sensibles). Las respuestas las da el servicio
  `ai`: con el agente si hay proveedor y clave configurados, o en modo básico con el
  texto del documento. Los datos sensibles detectados se pueden enviar a «Censura».
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { call } from '$lib/api.ts';
  import PasswordField from '$lib/components/PasswordField.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import Icon from '$lib/Icon.svelte';
  import { setStatus, toast } from '$lib/ui.ts';
  import { t } from '$texts';

  const T = t.viewer.ai;

  /** Dato sensible que propone el asistente (se puede enviar a «Censura»). */
  export interface Suggestion {
    texto: string;
    categoria: string;
    motivo?: string;
  }

  interface Message {
    role: 'user' | 'assistant' | 'error';
    text?: string;
    html?: string; // respuesta ya en HTML seguro (sin HTML crudo, imágenes ni enlaces)
    suggestions?: Suggestion[];
  }

  interface AiConfig {
    available: boolean; // están instaladas las bibliotecas del agente
    has_key: boolean;
    provider: string;
    model: string;
    providers: { id: string; label: string }[];
  }

  /** Respuesta de `ai.state`, `ai.chat`, `ai.summary`… */
  interface AiResult {
    config: AiConfig;
    messages: Message[];
  }

  /** `active`: la pestaña está a la vista; `redact([{ texto, tipo }])`: enviar a «Censura». */
  let { docId, active, close, redact }: {
    docId: number;
    active: boolean;
    close: () => void;
    redact: (items: Suggestion[]) => void;
  } = $props();

  let messages = $state.raw<Message[]>([]);
  let pending = $state<string | null>(null); // pregunta enviada, a la espera de respuesta
  let busy = $state(false);
  let loaded = false;
  let tab = $state(0);
  let question = $state('');
  let level = $state('medium');
  let list = $state<HTMLDivElement>();

  let config = $state.raw<AiConfig | null>(null);
  let settingsOpen = $state(false);
  let provider = $state('');
  let apiKey = $state('');
  let model = $state('');
  let modelPlaceholder = $state(T.model);
  let keyField = $state<PasswordField>();

  const ready = $derived(config && config.available && config.has_key);

  // La primera vez que la pestaña se ve, carga la conversación.
  $effect(() => {
    if (active && !loaded) {
      loaded = true;
      load(call<AiResult>('ai.state', docId));
    }
  });

  /** «Explicar con Agente IA» de la selección. */
  export function explain(text: string) {
    tab = 0;
    if (!loaded) {
      loaded = true;
      load(call<AiResult>('ai.state', docId));
    }
    question = T.explain(text.slice(0, 1500).trim());
    send();
  }

  function send() {
    const message = question.trim();
    if (!message || busy) return;
    question = '';
    runRequest(call<AiResult>('ai.chat', docId, message), message);
  }

  async function scrollDown() {
    await tick();
    if (list) list.scrollTop = list.scrollHeight;
  }

  async function load(request: Promise<AiResult>) {
    try {
      const result = await request;
      setConfig(result.config);
      messages = result.messages;
      scrollDown();
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  /** Muestra la pregunta enseguida y la respuesta cuando llega (las consultas tardan). */
  async function runRequest(request: Promise<AiResult>, asked: string | null = null) {
    if (busy) return;
    busy = true;
    pending = asked;
    scrollDown();
    try {
      const result = await request;
      setConfig(result.config);
      messages = [...messages, ...result.messages];
      tab = 0;
    } catch (err) {
      if (asked && !question) question = asked;
      toast((err as Error).message, 'danger');
    } finally {
      busy = false;
      pending = null;
      scrollDown();
    }
  }

  function sendToRedact(items: Suggestion[]) {
    redact(items);
    setStatus(T.sent(items.length));
  }

  // ── Proveedor y clave ──────────────────────────────────────────────────
  function setConfig(next: AiConfig) {
    config = next;
    provider = next.provider;
    model = next.model;
  }

  async function toggleSettings(show = !settingsOpen) {
    settingsOpen = show;
    await tick();
    if (show) keyField?.focus();
  }

  async function saveSettings() {
    try {
      const next = await call<AiConfig>('ai.set_config', provider, apiKey, model);
      apiKey = '';
      setConfig(next);
      setStatus(T.saved);
      toggleSettings(false);
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  function providerChanged() {
    model = '';
    modelPlaceholder = T.modelDefault;
  }

  function questionKey(ev: KeyboardEvent) {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    send();
  }

  const providerLabel = $derived(config?.providers.find((p) => p.id === config!.provider)?.label ?? config?.provider);
</script>

{#snippet button(icon: string, title: string, onclick: () => void)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {onclick}><Icon name={icon} /></button>
{/snippet}

{#snippet action(icon: string, label: string, onclick: () => void)}
  <button class="btn btn--block ai-action" type="button" disabled={busy} {onclick}><Icon name={icon} />{label}</button>
{/snippet}

{#snippet chat()}
  <div class="ai-chat">
    <div class="ai-messages" role="log" aria-live="polite" bind:this={list}>
      {#each messages as message, i (i)}
        {#if message.role === 'user'}
          <div class="ai-msg ai-msg--user">{message.text}</div>
        {:else if message.role === 'error'}
          <div class="ai-msg ai-msg--error"><Icon name="circle-alert" size={14} /><span>{message.text}</span></div>
        {:else}
          <div class="ai-msg ai-msg--assistant">
            <!-- HTML generado por el backend sin HTML crudo, imágenes ni enlaces (seguro) -->
            <div class="ai-msg__body">{@html message.html}</div>
            {#if message.suggestions?.length}
              <div class="ai-suggestions">
                {#each message.suggestions as s, j (j)}
                  <div class="ai-suggestion" title={s.motivo || ''}>
                    <span class="caption">[{s.categoria}]</span>
                    <span class="ai-suggestion__text">{s.texto}</span>
                    <button class="btn btn--sm" type="button" onclick={() => sendToRedact([s])}><Icon name="eraser" size={14} />{T.redact}</button>
                  </div>
                {/each}
                {#if message.suggestions.length > 1}
                  <button class="btn btn--sm btn--block" type="button" onclick={() => sendToRedact(message.suggestions!)}>
                    <Icon name="scissors" size={14} />{T.redactAll}
                  </button>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      {/each}
      {#if pending}<div class="ai-msg ai-msg--user">{pending}</div>{/if}
      {#if busy}
        <div class="ai-msg ai-msg--pending"><Icon name="sparkles" size={14} /> {T.thinking}</div>
      {:else if !messages.length}
        <div class="ai-welcome muted">
          <Icon name="sparkles" size={18} />
          <p>{T.welcome}</p>
        </div>
      {/if}
    </div>
    <div class="ai-input">
      <input bind:value={question} class="input" type="text" placeholder={T.question}
             aria-label={T.questionLabel} onkeydown={questionKey} />
      <button class="btn btn--primary btn--icon" type="button" title={T.send} aria-label={T.send} disabled={busy} onclick={send}>
        <Icon name="send" />
      </button>
    </div>
  </div>
{/snippet}

{#snippet actions()}
  <div class="ai-actions">
    {@render action('file-text', T.summary, () => runRequest(call<AiResult>('ai.summary', docId)))}
    {@render action('bar-chart', T.keyData, () => runRequest(call<AiResult>('ai.key_data', docId)))}
    <label class="field">
      <span class="caption">{T.sensitivity}</span>
      <select class="input select" aria-label={T.sensitivityLabel} bind:value={level}>
        {#each T.levels as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
    </label>
    {@render action('shield', T.sensitive, () => runRequest(call<AiResult>('ai.sensitive', docId, level)))}
  </div>
{/snippet}

<div class="ai-panel">
  <div class="ai-panel__head">
    <span class="ai-panel__icon"><Icon name="sparkles" size={20} /></span>
    <h2 class="heading">{T.title}</h2>
    {#if config}
      <span class="ai-badge" class:is-basic={!ready} title={ready ? T.agentTip(config.model) : T.basicTip}>
        {ready ? providerLabel : T.basic}
      </span>
    {/if}
    <span class="grow"></span>
    {@render button('trash', T.clear, () => load(call<AiResult>('ai.clear', docId)))}
    {@render button('settings', T.settings, () => toggleSettings())}
    {@render button('x', T.close, close)}
  </div>

  <div class="ai-settings" hidden={!settingsOpen}>
    <label class="field">
      <span class="caption">{T.provider}</span>
      <select class="input select" aria-label={T.provider} bind:value={provider} onchange={providerChanged}>
        {#each config?.providers ?? [] as p (p.id)}<option value={p.id}>{p.label}</option>{/each}
      </select>
    </label>
    <div class="field">
      <span class="caption">{T.apiKey}</span>
      <PasswordField bind:this={keyField} bind:value={apiKey} placeholder={T.apiKeyPlaceholder} />
    </div>
    <label class="field">
      <span class="caption">{T.model}</span>
      <input bind:value={model} class="input" type="text" placeholder={modelPlaceholder} aria-label={T.model} />
    </label>
    <p class="caption ai-settings__note">
      {#if !config?.available}
        {T.notInstalled}
      {:else if config.has_key}
        {T.hasKey}
      {:else}
        {T.noKey}
      {/if}
    </p>
    <div class="dialog__actions">
      <button class="btn" type="button" onclick={() => toggleSettings(false)}>{T.cancel}</button>
      <button class="btn btn--primary" type="button" onclick={saveSettings}><Icon name="check" />{T.save}</button>
    </div>
  </div>

  <SubTabs bind:current={tab} tabs={[
    { label: T.tabs.chat, icon: 'message-circle', panel: chat },
    { label: T.tabs.actions, icon: 'zap', panel: actions },
  ]} />
  <div class="progress progress--busy" hidden={!busy}><span></span></div>
</div>
