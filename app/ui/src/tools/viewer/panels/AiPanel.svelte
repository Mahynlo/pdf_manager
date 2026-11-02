<!--
  Pestaña «IA» del panel lateral (ai_dock.py en Qt): chat sobre el documento y acciones
  rápidas (resumen, datos clave, datos sensibles). Las respuestas las da el servicio
  `ai`: con el agente si hay proveedor y clave configurados, o en modo básico con el
  texto del documento. Los datos sensibles detectados se pueden enviar a «Censura».
-->
<script>
  import { tick } from 'svelte';
  import { call } from '$lib/api.js';
  import PasswordField from '$lib/components/PasswordField.svelte';
  import SubTabs from '$lib/components/SubTabs.svelte';
  import Icon from '$lib/Icon.svelte';
  import { setStatus, toast } from '$lib/ui.js';

  const LEVELS = [['low', 'Baja: solo datos críticos'], ['medium', 'Media: datos personales y financieros'], ['high', 'Alta: todo lo sensible']];

  /** `active`: la pestaña está a la vista; `redact([{ texto, tipo }])`: enviar a «Censura». */
  let { docId, active, close, redact } = $props();

  let messages = $state.raw([]);
  let pending = $state(null); // pregunta enviada, a la espera de respuesta
  let busy = $state(false);
  let loaded = false;
  let tab = $state(0);
  let question = $state('');
  let level = $state('medium');
  let list;

  let config = $state.raw(null);
  let settingsOpen = $state(false);
  let provider = $state('');
  let apiKey = $state('');
  let model = $state('');
  let modelPlaceholder = $state('Modelo');
  let keyField = $state();

  const ready = $derived(config && config.available && config.has_key);

  // La primera vez que la pestaña se ve, carga la conversación.
  $effect(() => {
    if (active && !loaded) {
      loaded = true;
      load(call('ai.state', docId));
    }
  });

  /** «Explicar con Agente IA» de la selección. */
  export function explain(text) {
    tab = 0;
    if (!loaded) {
      loaded = true;
      load(call('ai.state', docId));
    }
    question = `Explica el siguiente texto del documento: «${text.slice(0, 1500).trim()}»`;
    send();
  }

  function send() {
    const message = question.trim();
    if (!message || busy) return;
    question = '';
    runRequest(call('ai.chat', docId, message), message);
  }

  async function scrollDown() {
    await tick();
    if (list) list.scrollTop = list.scrollHeight;
  }

  async function load(request) {
    try {
      const result = await request;
      setConfig(result.config);
      messages = result.messages;
      scrollDown();
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  /** Muestra la pregunta enseguida y la respuesta cuando llega (las consultas tardan). */
  async function runRequest(request, asked = null) {
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
      toast(err.message, 'danger');
    } finally {
      busy = false;
      pending = null;
      scrollDown();
    }
  }

  function sendToRedact(items) {
    redact(items);
    setStatus(`${items.length} dato(s) enviado(s) a Censura`);
  }

  // ── Proveedor y clave ──────────────────────────────────────────────────
  function setConfig(next) {
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
      const next = await call('ai.set_config', provider, apiKey, model);
      apiKey = '';
      setConfig(next);
      setStatus('Configuración del asistente guardada');
      toggleSettings(false);
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  function providerChanged() {
    model = '';
    modelPlaceholder = 'Modelo (predeterminado del proveedor)';
  }

  const providerLabel = $derived(config?.providers.find((p) => p.id === config.provider)?.label ?? config?.provider);
</script>

{#snippet button(icon, title, onclick)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {onclick}><Icon name={icon} /></button>
{/snippet}

{#snippet action(icon, label, onclick)}
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
                    <button class="btn btn--sm" type="button" onclick={() => sendToRedact([s])}><Icon name="eraser" size={14} />Censurar</button>
                  </div>
                {/each}
                {#if message.suggestions.length > 1}
                  <button class="btn btn--sm btn--block" type="button" onclick={() => sendToRedact(message.suggestions)}>
                    <Icon name="scissors" size={14} />Enviar todo a Censura
                  </button>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      {/each}
      {#if pending}<div class="ai-msg ai-msg--user">{pending}</div>{/if}
      {#if busy}
        <div class="ai-msg ai-msg--pending"><Icon name="sparkles" size={14} /> Pensando…</div>
      {:else if !messages.length}
        <div class="ai-welcome muted">
          <Icon name="sparkles" size={18} />
          <p>Pregunta lo que quieras sobre el documento o usa las acciones rápidas.</p>
        </div>
      {/if}
    </div>
    <div class="ai-input">
      <input bind:value={question} class="input" type="text" placeholder="Haz una pregunta sobre el PDF..."
             aria-label="Pregunta sobre el PDF" onkeydown={(ev) => { if (ev.key === 'Enter') { ev.preventDefault(); send(); } }} />
      <button class="btn btn--primary btn--icon" type="button" title="Enviar" aria-label="Enviar" disabled={busy} onclick={send}>
        <Icon name="send" />
      </button>
    </div>
  </div>
{/snippet}

{#snippet actions()}
  <div class="ai-actions">
    {@render action('file-text', 'Generar Resumen Ejecutivo', () => runRequest(call('ai.summary', docId)))}
    {@render action('bar-chart', 'Extraer Datos Clave', () => runRequest(call('ai.key_data', docId)))}
    <label class="field">
      <span class="caption">Sensibilidad de la detección:</span>
      <select class="input select" aria-label="Sensibilidad" bind:value={level}>
        {#each LEVELS as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
    </label>
    {@render action('shield', 'Detectar Datos Sensibles', () => runRequest(call('ai.sensitive', docId, level)))}
  </div>
{/snippet}

<div class="ai-panel">
  <div class="ai-panel__head">
    <span class="ai-panel__icon"><Icon name="sparkles" size={20} /></span>
    <h2 class="heading">Asistente IA</h2>
    {#if config}
      <span class="ai-badge" class:is-basic={!ready}
            title={ready ? `Respuestas del agente (${config.model})` : 'Sin agente de IA: respuestas a partir del texto del documento'}>
        {ready ? providerLabel : 'Modo básico'}
      </span>
    {/if}
    <span class="grow"></span>
    {@render button('trash', 'Limpiar conversación', () => load(call('ai.clear', docId)))}
    {@render button('settings', 'Proveedor y clave de API', () => toggleSettings())}
    {@render button('x', 'Cerrar', close)}
  </div>

  <div class="ai-settings" hidden={!settingsOpen}>
    <label class="field">
      <span class="caption">Proveedor</span>
      <select class="input select" aria-label="Proveedor" bind:value={provider} onchange={providerChanged}>
        {#each config?.providers ?? [] as p (p.id)}<option value={p.id}>{p.label}</option>{/each}
      </select>
    </label>
    <div class="field">
      <span class="caption">Clave de API</span>
      <PasswordField bind:this={keyField} bind:value={apiKey} placeholder="Clave de API (se guarda en este equipo)" />
    </div>
    <label class="field">
      <span class="caption">Modelo</span>
      <input bind:value={model} class="input" type="text" placeholder={modelPlaceholder} aria-label="Modelo" />
    </label>
    <p class="caption ai-settings__note">
      {#if !config?.available}
        Las bibliotecas del agente de IA no están instaladas: el asistente responde en modo básico.
      {:else if config.has_key}
        Hay una clave guardada; escribe otra para cambiarla.
      {:else}
        Sin clave: el asistente responde en modo básico.
      {/if}
    </p>
    <div class="dialog__actions">
      <button class="btn" type="button" onclick={() => toggleSettings(false)}>Cancelar</button>
      <button class="btn btn--primary" type="button" onclick={saveSettings}><Icon name="check" />Guardar</button>
    </div>
  </div>

  <SubTabs bind:current={tab} tabs={[
    { label: 'Chat', icon: 'message-circle', panel: chat },
    { label: 'Acciones', icon: 'zap', panel: actions },
  ]} />
  <div class="progress progress--busy" hidden={!busy}><span></span></div>
</div>
