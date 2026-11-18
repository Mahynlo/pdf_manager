<!--
  Pestaña «IA» del panel lateral (ai_dock.py en Qt): un chat sobre el documento con las
  acciones rápidas (resumen, datos clave, datos sensibles) a mano sobre el cuadro de texto.
  Las respuestas las da el servicio `ai`: con el agente si hay un proveedor listo (Gemini u
  OpenAI con su clave, o una IA local con su dirección y modelo), o en modo básico con el
  texto del documento. Los datos sensibles detectados se pueden enviar a «Censura».
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { call } from '$lib/api.ts';
  import PasswordField from '$lib/components/PasswordField.svelte';
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.ts';
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

  interface Provider {
    id: string;
    label: string;
    needs_key: boolean;
    local: boolean; // dirección del servidor y contexto configurables
    base_url: string; // la de por defecto
    model: string; // el de por defecto ('' = hay que elegirlo)
  }

  interface AiConfig {
    available: boolean; // está instalado el cliente del agente
    has_key: boolean;
    provider: string;
    model: string;
    base_url: string;
    context: number;
    providers: Provider[];
  }

  /** Respuesta de `ai.state`, `ai.chat`, `ai.summary`… */
  interface AiResult {
    config: AiConfig;
    messages: Message[];
  }

  /** `active`: la pestaña está a la vista; `redact([{ texto, tipo }])`: enviar a «Censura». */
  let { docId, active, close, redact, syncText }: {
    docId: number;
    /** Python recibe el texto de las páginas al día antes de leerlo. */
    syncText: () => Promise<unknown>;
    active: boolean;
    close: () => void;
    redact: (items: Suggestion[]) => void;
  } = $props();

  let messages = $state.raw<Message[]>([]);
  let fresh = $state(0); // desde qué mensaje entran con animación (los cargados al abrir, no)
  let pending = $state<string | null>(null); // lo pedido, a la espera de respuesta
  let busy = $state(false);
  let elapsed = $state(0); // segundos esperando la respuesta
  let retry = $state<(() => void) | null>(null); // repetir lo último si el proveedor falló
  let copied = $state(-1); // mensaje recién copiado (muestra la marca un momento)
  let atBottom = $state(true);
  let loaded = false;
  let question = $state('');
  let level = $state('medium');
  let list = $state<HTMLDivElement>();
  let field = $state<HTMLTextAreaElement>();

  let config = $state.raw<AiConfig | null>(null);
  let settingsOpen = $state(false);
  let provider = $state('');
  let apiKey = $state('');
  let model = $state('');
  let baseUrl = $state('');
  let context = $state(0);
  let models = $state.raw<string[]>([]); // los que ofrece el servidor («Buscar modelos»)
  let searching = $state(false);
  let providerField = $state<HTMLSelectElement>();

  /** El proveedor elegido en el formulario. */
  const chosen = $derived(config?.providers.find((p) => p.id === provider));
  const ready = $derived.by(() => {
    const current = config?.providers.find((p) => p.id === config!.provider);
    return !!(config?.available && current && config.model && (config.has_key || !current.needs_key));
  });
  const providerLabel = $derived(config?.providers.find((p) => p.id === config!.provider)?.label ?? config?.provider);
  const empty = $derived(!messages.length && !busy);

  // La primera vez que la pestaña se ve, carga la conversación.
  $effect(() => {
    if (active && !loaded) {
      loaded = true;
      load(call<AiResult>('ai.state', docId));
    }
  });

  // Cuenta los segundos de espera (los modelos locales pueden tardar).
  $effect(() => {
    if (!busy) return;
    const started = Date.now();
    elapsed = 0;
    const timer = setInterval(() => (elapsed = Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  });

  // ── Peticiones ─────────────────────────────────────────────────────────
  /** Pregunta al asistente (`method` del servicio `ai`), con el texto del documento al día en Python. */
  const ask = (method: string, ...args: unknown[]) => syncText().then(() => call<AiResult>(method, docId, ...args));

  async function load(request: Promise<AiResult>) {
    try {
      const result = await request;
      setConfig(result.config);
      messages = result.messages;
      fresh = messages.length;
      retry = null;
      toBottom(false);
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  /**
   * Muestra lo pedido enseguida y la respuesta cuando llega (las consultas tardan).
   * `start` crea la petición: si el proveedor falla, «Reintentar» la repite.
   */
  async function runRequest(start: () => Promise<AiResult>, shown: string, typed = false) {
    if (busy) return;
    busy = true;
    pending = shown;
    retry = null;
    toBottom();
    try {
      const result = await start();
      setConfig(result.config);
      messages = [...messages, ...result.messages];
      if (result.messages.at(-1)?.role === 'error') retry = () => runRequest(start, shown, typed);
    } catch (err) {
      if (typed && !question) question = shown; // no se pierde lo escrito
      toast((err as Error).message, 'danger');
    } finally {
      busy = false;
      pending = null;
      reveal();
    }
  }

  function send() {
    const message = question.trim();
    if (!message || busy) return;
    question = '';
    runRequest(() => ask('ai.chat', message), message, true);
  }

  const summary = () => runRequest(() => ask('ai.summary'), T.summary);
  const keyData = () => runRequest(() => ask('ai.key_data'), T.keyData);

  function sensitive(value = level) {
    level = value;
    runRequest(() => ask('ai.sensitive', value), T.sensitive);
  }

  /** «Datos sensibles» pregunta antes con qué sensibilidad buscar. */
  function sensitiveMenu(ev: MouseEvent) {
    openMenu(ev.currentTarget as Element, T.levels.map(([value, label]) => (
      { label, checked: value === level, onSelect: () => sensitive(value) })));
  }

  /** «Explicar con Agente IA» de la selección. */
  export function explain(text: string) {
    if (!loaded) {
      loaded = true;
      load(call<AiResult>('ai.state', docId));
    }
    question = T.explain(text.slice(0, 1500).trim());
    send();
  }

  function sendToRedact(items: Suggestion[]) {
    redact(items);
    setStatus(T.sent(items.length));
  }

  async function copy(message: Message, i: number) {
    try {
      await navigator.clipboard.writeText(message.text ?? '');
      copied = i;
      setStatus(T.copied);
      setTimeout(() => copied === i && (copied = -1), 1500);
    } catch (err) {
      toast(T.copyError((err as Error).message), 'danger');
    }
  }

  // ── Desplazamiento ─────────────────────────────────────────────────────
  const motion = (): ScrollBehavior => (matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth');

  function scrolled() {
    if (list) atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 48;
  }

  async function toBottom(smooth = true) {
    await tick();
    list?.scrollTo({ top: list.scrollHeight, behavior: smooth ? motion() : 'auto' });
  }

  /** La respuesta nueva desde su principio: las largas no saltan al final. */
  async function reveal() {
    await tick();
    const last = [...(list?.querySelectorAll<HTMLElement>('.ai-row') ?? [])].at(-1);
    if (list && last) list.scrollTo({ top: last.offsetTop - 8, behavior: motion() });
  }

  function questionKey(ev: KeyboardEvent) {
    if (ev.key !== 'Enter' || ev.shiftKey || ev.isComposing) return; // Mayús+Intro: salto de línea
    ev.preventDefault();
    send();
  }

  // ── Proveedor y clave ──────────────────────────────────────────────────
  function setConfig(next: AiConfig) {
    config = next;
    if (settingsOpen) return; // no pisa lo que se está escribiendo
    provider = next.provider;
    model = next.model;
    baseUrl = next.base_url;
    context = next.context;
  }

  async function toggleSettings(show = !settingsOpen) {
    settingsOpen = show;
    if (!show && config) setConfig(config); // al cancelar, vuelve lo guardado
    await tick();
    if (show) providerField?.focus();
  }

  async function saveSettings() {
    try {
      const local = chosen?.local;
      const next = await call<AiConfig>('ai.set_config', provider, apiKey, model,
                                        local ? baseUrl : null, local ? context : null);
      apiKey = '';
      settingsOpen = false;
      setConfig(next);
      setStatus(T.saved);
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  /** Al cambiar de proveedor, sus valores (los guardados si es el configurado). */
  function providerChanged() {
    const saved = config && provider === config.provider;
    model = saved ? config!.model : '';
    baseUrl = saved ? config!.base_url : (chosen?.base_url ?? '');
    apiKey = '';
    models = [];
  }

  async function searchModels() {
    searching = true;
    try {
      models = await call<string[]>('ai.models', provider, chosen?.local ? baseUrl : null, apiKey);
      setStatus(T.modelsFound(models.length));
    } catch (err) {
      toast((err as Error).message, 'danger');
    } finally {
      searching = false;
    }
  }

  /** La nota bajo el formulario: qué falta para que responda el agente. */
  const note = $derived.by(() => {
    if (!config?.available) return T.notInstalled;
    if (chosen?.local) return model.trim() ? T.localReady : T.localNoModel;
    if (provider === config.provider && config.has_key) return T.hasKey;
    return T.noKey;
  });
</script>

{#snippet button(icon: string, title: string, onclick: () => void)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {onclick}><Icon name={icon} /></button>
{/snippet}

{#snippet avatar(icon = 'sparkles')}
  <span class="ai-avatar" aria-hidden="true"><Icon name={icon} size={13} /></span>
{/snippet}

{#snippet starter(icon: string, title: string, text: string, onclick: (ev: MouseEvent) => void)}
  <button class="ai-starter" type="button" {onclick}>
    <span class="ai-starter__icon"><Icon name={icon} /></span>
    <span class="ai-starter__text"><strong>{title}</strong><span>{text}</span></span>
  </button>
{/snippet}

{#snippet chip(icon: string, label: string, onclick: (ev: MouseEvent) => void, menu = false)}
  <button class="ai-chip" type="button" disabled={busy} {onclick} aria-haspopup={menu ? 'menu' : undefined}>
    <Icon name={icon} size={14} />{label}{#if menu}<Icon name="chevron-down" size={12} />{/if}
  </button>
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
    {#if messages.length}{@render button('trash', T.clear, () => load(call<AiResult>('ai.clear', docId)))}{/if}
    {@render button('settings', T.settings, () => toggleSettings())}
    {@render button('x', T.close, close)}
  </div>

  <div class="ai-settings" hidden={!settingsOpen}>
    <label class="field">
      <span class="caption">{T.provider}</span>
      <select class="input select" aria-label={T.provider} bind:this={providerField} bind:value={provider}
              onchange={providerChanged}>
        {#each config?.providers ?? [] as p (p.id)}<option value={p.id}>{p.label}</option>{/each}
      </select>
    </label>
    {#if chosen?.local}
      <label class="field">
        <span class="caption">{T.baseUrl}</span>
        <input bind:value={baseUrl} class="input" type="url" placeholder={chosen.base_url} aria-label={T.baseUrl}
               spellcheck="false" autocomplete="off" />
        <span class="caption muted">{T.baseUrlHint}</span>
      </label>
    {/if}
    <div class="field">
      <span class="caption">{chosen?.needs_key === false ? T.apiKeyOptional : T.apiKey}</span>
      <PasswordField bind:value={apiKey} placeholder={T.apiKeyPlaceholder} />
    </div>
    <div class="field">
      <span class="caption">{T.model}</span>
      <div class="ai-settings__row">
        <input bind:value={model} class="input" type="text" list="ai-models" aria-label={T.model}
               placeholder={chosen?.model || T.modelPick} spellcheck="false" autocomplete="off" />
        <button class="btn" type="button" title={T.searchModelsTip} disabled={searching || !config?.available}
                onclick={searchModels}><Icon name="search" />{T.searchModels}</button>
      </div>
      <datalist id="ai-models">{#each models as name (name)}<option value={name}></option>{/each}</datalist>
    </div>
    {#if chosen?.local}
      <label class="field">
        <span class="caption">{T.context}</span>
        <input bind:value={context} class="input" type="number" min="2048" step="1024" aria-label={T.context} />
        <span class="caption muted">{T.contextHint}</span>
      </label>
    {/if}
    <p class="caption ai-settings__note">{note}</p>
    <div class="dialog__actions">
      <button class="btn" type="button" onclick={() => toggleSettings(false)}>{T.cancel}</button>
      <button class="btn btn--primary" type="button" onclick={saveSettings}><Icon name="check" />{T.save}</button>
    </div>
  </div>

  <div class="ai-chat">
    <div class="ai-messages" role="log" aria-live="polite" aria-busy={busy} bind:this={list} onscroll={scrolled}>
      {#if empty}
        <div class="ai-welcome">
          <span class="ai-welcome__icon"><Icon name="sparkles" size={22} /></span>
          <h3 class="ai-welcome__title">{T.welcomeTitle}</h3>
          <p class="ai-welcome__text muted">{T.welcome}</p>
          <div class="ai-starters">
            {@render starter('file-text', T.summary, T.summaryTip, summary)}
            {@render starter('bar-chart', T.keyData, T.keyDataTip, keyData)}
            {@render starter('shield', T.sensitive, T.sensitiveTip, sensitiveMenu)}
            {@render starter('message-circle', T.about, T.aboutTip, () => { question = T.aboutQuestion; send(); })}
          </div>
        </div>
      {/if}

      {#each messages as message, i (i)}
        {#if message.role === 'user'}
          <div class="ai-row ai-row--user" class:is-new={i >= fresh}>
            <div class="ai-msg ai-msg--user">{message.text}</div>
          </div>
        {:else if message.role === 'error'}
          <div class="ai-row" class:is-new={i >= fresh}>
            {@render avatar('circle-alert')}
            <div class="ai-row__main">
              <div class="ai-msg ai-msg--error">{message.text}</div>
              {#if retry && !busy && i === messages.length - 1}
                <div class="ai-msg__tools is-shown">
                  <button class="btn btn--sm" type="button" onclick={retry}><Icon name="rotate-cw" size={14} />{T.retry}</button>
                </div>
              {/if}
            </div>
          </div>
        {:else}
          <div class="ai-row" class:is-new={i >= fresh}>
            {@render avatar()}
            <div class="ai-row__main">
              <div class="ai-msg ai-msg--assistant">
                <!-- HTML generado por el backend sin HTML crudo, imágenes ni enlaces (seguro) -->
                <div class="ai-msg__body">{@html message.html}</div>
                {#if message.suggestions?.length}
                  <div class="ai-suggestions">
                    {#each message.suggestions as s, j (j)}
                      <div class="ai-suggestion" title={s.motivo || ''}>
                        <span class="ai-suggestion__tag">{s.categoria}</span>
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
              <div class="ai-msg__tools">
                <button class="btn btn--icon btn--sm" type="button" title={T.copy} aria-label={T.copy}
                        onclick={() => copy(message, i)}><Icon name={copied === i ? 'check' : 'copy'} size={14} /></button>
              </div>
            </div>
          </div>
        {/if}
      {/each}

      {#if busy}
        {#if pending}
          <div class="ai-row ai-row--user is-new"><div class="ai-msg ai-msg--user">{pending}</div></div>
        {/if}
        <div class="ai-row ai-row--typing is-new">
          {@render avatar()}
          <div class="ai-msg ai-msg--assistant ai-typing">
            <span class="ai-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            <span class="ai-typing__label">{elapsed < 3 ? T.reading : T.thinking(elapsed)}</span>
          </div>
        </div>
      {/if}
    </div>

    <div class="ai-composer">
      {#if !atBottom}
        <button class="ai-jump" type="button" title={T.toBottom} aria-label={T.toBottom} onclick={() => toBottom()}>
          <Icon name="arrow-down" size={16} />
        </button>
      {/if}
      {#if !empty}
        <div class="ai-chips" role="toolbar" aria-label={T.quick}>
          {@render chip('file-text', T.summaryShort, summary)}
          {@render chip('bar-chart', T.keyDataShort, keyData)}
          {@render chip('shield', T.sensitiveShort, sensitiveMenu, true)}
        </div>
      {/if}
      <div class="ai-input" class:is-busy={busy}>
        <textarea bind:this={field} bind:value={question} class="ai-input__field" rows="1" placeholder={T.question}
                  aria-label={T.questionLabel} title={T.questionTip} onkeydown={questionKey}></textarea>
        <button class="ai-input__send" type="button" title={T.send} aria-label={T.send}
                disabled={busy || !question.trim()} onclick={() => { send(); field?.focus(); }}>
          <Icon name="arrow-up" size={16} />
        </button>
      </div>
    </div>
  </div>
</div>
