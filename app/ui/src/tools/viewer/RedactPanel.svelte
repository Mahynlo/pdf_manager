<!--
  Pestaña «Censura» del panel lateral (redact_panel.py y redact_widgets.py en Qt):
  términos, patrones predefinidos, selecciones y áreas marcadas en la página, perfiles
  guardados y aplicación definitiva.

  Lo que se va a censurar son las marcas de la página (redaction.js): cada término pone una
  marca en cada sitio donde aparece (lo busca el servicio `redact`), y también la selección
  enviada desde la página y la herramienta «Marcar». Cada marca se revisa en la página: se
  mueve, se borra (Supr) o se deshace (Ctrl+Z). La lista agrupa las marcas por lo que las puso.
  Las opciones de búsqueda, el color y el perfil activo los guarda el servicio.
-->
<script>
  import { call } from '$lib/api.js';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.js';
  import { askText, confirmDialog, openModal, setStatus, toast } from '$lib/ui.js';
  import { TOOLS } from './canvas.js';
  import ProfilesDialog from './ProfilesDialog.svelte';

  // Colores de relleno (los mismos que Qt).
  const COLORS = [
    ['#000000', 'Negro'],
    ['#B71C1C', 'Rojo oscuro'],
    ['#0D47A1', 'Azul marino'],
    ['#1B5E20', 'Verde oscuro'],
    ['#FFFFFF', 'Blanco'],
    ['#616161', 'Gris'],
  ];

  /**
   * `marks`: las marcas (redaction.js); `tool`, `setTool(t)`: herramienta del lienzo (para
   * «Marcar»); `show(marca)`: ir a una marca y seleccionarla; `commit(fn)`: ejecutar
   * `fn(página)` → [info, página] en la cola de cambios del documento (antes, las marcas
   * pasan a Python con las anotaciones).
   */
  let { docId, marks, tool, setTool, close, show, commit } = $props();

  let redact = $state.raw(null); // opciones, color y perfil activo
  let groups = $state.raw([]);
  let term = $state('');
  let cycle = new Map(); // grupo -> siguiente marca al hacer clic

  const total = $derived(groups.reduce((n, group) => n + group.marks.length, 0));
  const pages = $derived(new Set(groups.flatMap((group) => group.marks.map((mark) => mark.pageIndex))).size);
  const marking = $derived(tool === TOOLS.REDACT);

  // La lista sigue a las marcas: cualquier cambio (también deshacer) la rehace.
  $effect(() => {
    let frame = 0;
    const stop = marks.annotations.watch(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => (groups = marks.groups()));
    });
    groups = marks.groups();
    return () => {
      cancelAnimationFrame(frame);
      stop();
    };
  });

  // ── Estado ─────────────────────────────────────────────────────────────
  /** Vuelve a pedir las opciones, el color y el perfil activo. */
  export async function refresh() {
    await run(async () => setState(await call('redact.state', docId)));
  }

  /** Marca dónde aparece una frase o patrón (también desde la búsqueda y la IA). */
  export async function addTerm(value) {
    await run(async () => {
      const results = await call('redact.find', docId, [value]);
      const found = results.reduce((n, r) => n + r.matches.length, 0);
      if (!found) toast(`No se encontró «${value}» en el documento.`, 'info');
      marks.addMatches(results, results.map((r) => r.term)); // otra vez el mismo término: se busca de nuevo
    });
  }

  function setState(next) {
    redact = next;
    marks.annotations.style.redactColor = next.color; // para las marcas nuevas
  }

  async function run(fn) {
    try {
      await fn();
    } catch (err) {
      toast(err.message, 'danger');
    }
  }

  /** Busca de nuevo los términos de la lista (cambiaron las opciones o el perfil). */
  async function findAgain(terms, replace = terms) {
    marks.addMatches(terms.length ? await call('redact.find', docId, terms) : [], replace);
  }

  function setOption(name, value) {
    if (!redact) return;
    const next = { case_sensitive: redact.case_sensitive, whole_word: redact.whole_word, search_ocr: redact.search_ocr, [name]: value };
    run(async () => {
      setState(await call('redact.set_options', docId, next.case_sensitive, next.whole_word, next.search_ocr));
      await findAgain(marks.terms());
    });
  }

  function setColor(color) {
    run(async () => {
      setState(await call('redact.set_color', docId, color));
      marks.setColor(color);
    });
  }

  function onkeydown(ev) {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    const value = term.trim();
    term = '';
    if (value) addTerm(value);
  }

  function next(group) {
    const i = cycle.get(group.key) ?? 0;
    cycle.set(group.key, (i + 1) % group.marks.length);
    show(group.marks[i % group.marks.length]);
  }

  async function patterns(ev) {
    const anchor = ev.currentTarget;
    await run(async () => {
      const list = await call('redact.patterns');
      openMenu(anchor, list.map(({ label, pattern }) => ({ label, onSelect: () => addTerm(pattern) })));
    });
  }

  // ── Aplicar ────────────────────────────────────────────────────────────
  async function apply() {
    if (!total) {
      toast('No hay marcas de censura en el documento.', 'warning');
      return;
    }
    const ok = await confirmDialog('Confirmar Censura Permanente',
      `Se aplicará censura permanente sobre ${total} marca(s) en el documento.\n\n`
      + 'Esta operación eliminará irreversiblemente el texto y gráficos subyacentes.\n¿Deseas continuar?');
    if (!ok) return;
    if (marking) setTool(TOOLS.SELECT);
    await commit(async (page) => {
      const { info, count } = await call('redact.apply', docId);
      setState(await call('redact.state', docId));
      setStatus(`Censura aplicada en ${count} marca(s). Usa 'Guardar PDF como…' para crear la copia censurada.`);
      return [info, page];
    });
  }

  // ── Perfiles ───────────────────────────────────────────────────────────
  async function saveProfile() {
    const terms = marks.terms();
    if (!terms.length) {
      toast('Añade al menos un término para guardar el perfil.', 'warning');
      return;
    }
    let name = null;
    if (!redact?.profile) {
      name = await askText('Guardar Perfil', 'Nombre del nuevo perfil de censura:');
      if (!name?.trim()) return;
    }
    await run(async () => {
      setState(await call('redact.save_profile', docId, terms, name));
      if (!name) setStatus(`Se han guardado los cambios en el perfil «${redact.profile.name}».`);
    });
  }

  /** Cargar un perfil: sus términos sustituyen a los de la lista (las selecciones y áreas se quedan). */
  async function openProfiles() {
    const id = await openModal(ProfilesDialog, { active: redact?.profile?.id, refresh });
    if (!id) return;
    await run(async () => {
      const { state, terms } = await call('redact.load_profile', docId, id);
      setState(state);
      marks.setColor(state.color);
      await findAgain(terms, marks.terms());
    });
  }

  refresh();
</script>

{#snippet button(icon, title, onclick)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {onclick}><Icon name={icon} /></button>
{/snippet}

{#snippet toggle(label, title, checked, onclick)}
  <button class="btn btn--icon btn--sm redact-panel__toggle" class:is-checked={checked} type="button" {title}
          aria-label={title} aria-pressed={checked} {onclick}>{label}</button>
{/snippet}

<div class="redact-panel">
  <div class="redact-panel__head">
    <span class="redact-panel__icon"><Icon name="eraser" size={20} /></span>
    <h2 class="heading">Censura</h2>
    <span class="grow"></span>
    {@render button('x', 'Cerrar', close)}
  </div>
  <div class="redact-panel__profile">
    <Icon name="folder" />
    <span class="redact-panel__profile-name caption" class:is-active={redact?.profile}>
      {redact?.profile ? `«${redact.profile.name}»` : 'Sin perfil'}
    </span>
    {@render button('save', 'Guardar cambios en el perfil actual', saveProfile)}
    {@render button('settings', 'Gestionar perfiles de censura', openProfiles)}
  </div>
  <span class="caption">Agregar texto o patrón a censurar</span>
  <div class="redact-panel__row">
    <input bind:value={term} class="input" type="text" placeholder="Escribe una frase o regex y pulsa Enter..."
           aria-label="Texto o patrón a censurar" {onkeydown} />
    {@render toggle('Aa', 'Distinguir mayúsculas/minúsculas', redact?.case_sensitive,
                    () => setOption('case_sensitive', !redact.case_sensitive))}
    {@render toggle('W', 'Palabra completa (evita coincidir dentro de otras palabras)', redact?.whole_word,
                    () => setOption('whole_word', !redact.whole_word))}
    <button class="btn btn--icon btn--sm" type="button" title="Patrones predefinidos (DNI, correos, tarjetas, teléfonos...)"
            aria-label="Patrones predefinidos" onclick={patterns}><Icon name="zap" /></button>
  </div>
  <Checkbox label="Buscar en capas OCR" checked={redact?.search_ocr ?? true}
            onchange={(ev) => setOption('search_ocr', ev.currentTarget.checked)} />
  <button class="btn btn--block redact-panel__mark" class:is-checked={marking} type="button" aria-pressed={marking}
          title="Arrastra sobre el texto o alrededor de un área para marcarlo (Esc para terminar)"
          onclick={() => setTool(marking ? TOOLS.SELECT : TOOLS.REDACT)}>
    <Icon name="square-dashed" />{marking ? 'Marcando: arrastra sobre la página' : 'Marcar texto o área en la página'}
  </button>
  <div class="redact-panel__row">
    <Icon name="list" /><h3 class="heading">Lista de censuras</h3>
    <span class="grow"></span>
    <span class="caption">{total ? `${total} marca(s) en ${pages} pág.` : 'Sin marcas'}</span>
    {@render button('trash', 'Quitar todas las marcas', () => marks.remove(marks.all()))}
  </div>
  <div class="redact-terms" role="list" aria-label="Lista de censuras">
    {#each groups as group (group.key)}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
      <div class="redact-term" role="listitem" title="Clic para ir a sus marcas:&#10;{group.label}" onclick={() => next(group)}>
        <span class="redact-term__dot" style:--swatch={redact?.color} aria-hidden="true"></span>
        <span class="redact-term__text"><span class="caption">[{group.kind}]</span> {group.label}</span>
        <span class="redact-term__count">{group.marks.length}</span>
        <button class="btn btn--icon btn--sm" type="button" title="Quitar sus marcas" aria-label="Quitar sus marcas"
                onclick={(ev) => { ev.stopPropagation(); marks.remove(group.marks); }}>
          <Icon name="x" size={14} />
        </button>
      </div>
    {:else}
      <p class="redact-terms__empty muted">Sin marcas — escribe una frase, usa ⚡ Patrones o marca en la página</p>
    {/each}
  </div>
  <div class="redact-panel__row">
    <span class="caption">Color</span>
    {#each COLORS as [color, name] (color)}
      <button class="redact-swatch" class:is-checked={color === redact?.color} type="button" title="Color {name}"
              aria-label="Color {name}" style:--swatch={color} onclick={() => setColor(color)}></button>
    {/each}
  </div>
  <button class="btn btn--danger btn--block btn--lg" type="button" onclick={apply}><Icon name="scissors" />Aplicar censura al documento</button>
</div>
