<!--
  Pestaña «Censura» del panel lateral (redact_panel.py y redact_widgets.py en Qt):
  términos, patrones predefinidos, selecciones y áreas marcadas en la página, perfiles
  guardados y aplicación definitiva.

  Lo que se va a censurar son las marcas de la página (redaction.ts): cada término pone una
  marca en cada sitio donde aparece (lo busca el servicio `redact`), y también la selección
  enviada desde la página y la herramienta «Marcar». Cada marca se revisa en la página: se
  mueve, se borra (Supr) o se deshace (Ctrl+Z). La lista agrupa las marcas por lo que las puso.
  Las opciones de búsqueda, el color y el perfil activo los guarda el servicio.
-->
<script lang="ts">
  import type { PdfRedactAnnoObject } from '@embedpdf/models';
  import { call } from '$lib/api.ts';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.ts';
  import type { DocumentInfo } from '$lib/types.ts';
  import { askText, confirmDialog, openModal, setStatus, toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import { TOOLS } from '../canvas/canvas.ts';
  import type { Change } from '../document/operations.ts';
  import ProfilesDialog from './ProfilesDialog.svelte';
  import type { FindResult, RedactGroup, RedactionMarks } from './redaction.ts';

  /** Opciones, color y perfil activo: `redact.state` y lo que los cambia. */
  interface RedactState {
    case_sensitive: boolean;
    whole_word: boolean;
    search_ocr: boolean;
    color: string;
    profile: { id: string; name: string } | null;
  }

  const T = t.viewer.redact;

  /**
   * `marks`: las marcas (redaction.ts); `tool`, `setTool(t)`: herramienta del lienzo (para
   * «Marcar»); `show(marca)`: ir a una marca y seleccionarla; `commit(fn)`: ejecutar
   * `fn(página)` → [info, página] en la cola de cambios del documento (antes, las marcas
   * pasan a Python con las anotaciones).
   */
  let { docId, marks, tool, setTool, close, show, commit, syncDocument }: {
    docId: number;
    /** Python recibe el documento al día (páginas y anotaciones) antes de leerlo. */
    syncDocument: () => Promise<unknown>;
    marks: RedactionMarks;
    tool: string;
    setTool: (tool: string) => void;
    close: () => void;
    show: (mark: PdfRedactAnnoObject) => void;
    commit: (fn: (page: number) => Promise<Change>) => Promise<unknown>;
  } = $props();

  let redact = $state.raw<RedactState | null>(null);
  let groups = $state.raw<RedactGroup[]>([]);
  let term = $state('');
  const cycle = new Map<string, number>(); // grupo -> siguiente marca al hacer clic

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
    await run(async () => setState(await call<RedactState>('redact.state', docId)));
  }

  /** Marca dónde aparece una frase o patrón (también desde la búsqueda y la IA). */
  export async function addTerm(value: string) {
    await run(async () => {
      await syncDocument();
      const results = await call<FindResult[]>('redact.find', docId, [value]);
      const found = results.reduce((n, r) => n + r.matches.length, 0);
      if (!found) toast(T.notFound(value), 'info');
      marks.addMatches(results, results.map((r) => r.term)); // otra vez el mismo término: se busca de nuevo
    });
  }

  function setState(next: RedactState) {
    redact = next;
    marks.annotations.style.redactColor = next.color; // para las marcas nuevas
  }

  async function run(fn: () => Promise<void>) {
    try {
      await fn();
    } catch (err) {
      toast((err as Error).message, 'danger');
    }
  }

  /** Busca de nuevo los términos de la lista (cambiaron las opciones o el perfil). */
  async function findAgain(terms: string[], replace = terms) {
    if (terms.length) await syncDocument();
    marks.addMatches(terms.length ? await call<FindResult[]>('redact.find', docId, terms) : [], replace);
  }

  function setOption(name: 'case_sensitive' | 'whole_word' | 'search_ocr', value: boolean) {
    if (!redact) return;
    const next = { case_sensitive: redact.case_sensitive, whole_word: redact.whole_word, search_ocr: redact.search_ocr, [name]: value };
    run(async () => {
      setState(await call<RedactState>('redact.set_options', docId, next.case_sensitive, next.whole_word, next.search_ocr));
      await findAgain(marks.terms());
    });
  }

  function setColor(color: string) {
    run(async () => {
      setState(await call<RedactState>('redact.set_color', docId, color));
      marks.setColor(color);
    });
  }

  function onkeydown(ev: KeyboardEvent) {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    const value = term.trim();
    term = '';
    if (value) addTerm(value);
  }

  function next(group: RedactGroup) {
    const i = cycle.get(group.key) ?? 0;
    cycle.set(group.key, (i + 1) % group.marks.length);
    show(group.marks[i % group.marks.length]);
  }

  async function patterns(ev: MouseEvent & { currentTarget: HTMLButtonElement }) {
    const anchor = ev.currentTarget;
    await run(async () => {
      const list = await call<{ label: string; pattern: string }[]>('redact.patterns');
      openMenu(anchor, list.map(({ label, pattern }) => ({ label, onSelect: () => addTerm(pattern) })));
    });
  }

  // ── Aplicar ────────────────────────────────────────────────────────────
  async function apply() {
    if (!total) {
      toast(T.noMarksToApply, 'warning');
      return;
    }
    if (!(await confirmDialog(T.confirmTitle, T.confirm(total)))) return;
    if (marking) setTool(TOOLS.SELECT);
    await commit(async (page) => {
      const { info, count } = await call<{ info: DocumentInfo; count: number }>('redact.apply', docId);
      setState(await call<RedactState>('redact.state', docId));
      setStatus(T.applied(count));
      return [info, page];
    });
  }

  // ── Perfiles ───────────────────────────────────────────────────────────
  async function saveProfile() {
    const terms = marks.terms();
    if (!terms.length) {
      toast(T.needTerm, 'warning');
      return;
    }
    let name: string | null = null;
    if (!redact?.profile) {
      name = await askText(T.saveProfileTitle, T.saveProfileLabel);
      if (!name?.trim()) return;
    }
    await run(async () => {
      setState(await call<RedactState>('redact.save_profile', docId, terms, name));
      if (!name && redact?.profile) setStatus(T.profileSaved(redact.profile.name));
    });
  }

  /** Cargar un perfil: sus términos sustituyen a los de la lista (las selecciones y áreas se quedan). */
  async function openProfiles() {
    const id = await openModal<string>(ProfilesDialog, { active: redact?.profile?.id, refresh });
    if (!id) return;
    await run(async () => {
      const { state, terms } = await call<{ state: RedactState; terms: string[] }>('redact.load_profile', docId, id);
      setState(state);
      marks.setColor(state.color);
      await findAgain(terms, marks.terms());
    });
  }

  refresh();
</script>

{#snippet button(icon: string, title: string, onclick: () => void)}
  <button class="btn btn--icon btn--sm" type="button" {title} aria-label={title} {onclick}><Icon name={icon} /></button>
{/snippet}

{#snippet toggle(label: string, title: string, checked: boolean | undefined, onclick: () => void)}
  <button class="btn btn--icon btn--sm redact-panel__toggle" class:is-checked={checked} type="button" {title}
          aria-label={title} aria-pressed={checked} {onclick}>{label}</button>
{/snippet}

<div class="redact-panel">
  <div class="redact-panel__head">
    <span class="redact-panel__icon"><Icon name="eraser" size={20} /></span>
    <h2 class="heading">{T.title}</h2>
    <span class="grow"></span>
    {@render button('x', T.close, close)}
  </div>
  <div class="redact-panel__profile">
    <Icon name="folder" />
    <span class="redact-panel__profile-name caption" class:is-active={redact?.profile}>
      {redact?.profile ? T.profileName(redact.profile.name) : T.noProfile}
    </span>
    {@render button('save', T.saveProfile, saveProfile)}
    {@render button('settings', T.manageProfiles, openProfiles)}
  </div>
  <span class="caption">{T.addTerm}</span>
  <div class="redact-panel__row">
    <input bind:value={term} class="input" type="text" placeholder={T.termPlaceholder}
           aria-label={T.termLabel} {onkeydown} />
    {@render toggle('Aa', T.caseSensitive, redact?.case_sensitive, () => setOption('case_sensitive', !redact?.case_sensitive))}
    {@render toggle('W', T.wholeWord, redact?.whole_word, () => setOption('whole_word', !redact?.whole_word))}
    <button class="btn btn--icon btn--sm" type="button" title={T.patternsTip}
            aria-label={T.patterns} onclick={patterns}><Icon name="zap" /></button>
  </div>
  <Checkbox label={T.searchOcr} checked={redact?.search_ocr ?? true}
            onchange={(ev) => setOption('search_ocr', ev.currentTarget.checked)} />
  <button class="btn btn--block redact-panel__mark" class:is-checked={marking} type="button" aria-pressed={marking}
          title={T.markTip} onclick={() => setTool(marking ? TOOLS.SELECT : TOOLS.REDACT)}>
    <Icon name="square-dashed" />{marking ? T.marking : T.mark}
  </button>
  <div class="redact-panel__row">
    <Icon name="list" /><h3 class="heading">{T.list}</h3>
    <span class="grow"></span>
    <span class="caption">{total ? T.summary(total, pages) : T.noMarks}</span>
    {@render button('trash', T.removeAll, () => marks.remove(marks.all()))}
  </div>
  <div class="redact-terms" role="list" aria-label={T.list}>
    {#each groups as group (group.key)}
      <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
      <div class="redact-term" role="listitem" title={T.groupTip(group.label)} onclick={() => next(group)}>
        <span class="redact-term__dot" style:--swatch={redact?.color} aria-hidden="true"></span>
        <span class="redact-term__text"><span class="caption">[{group.kind}]</span> {group.label}</span>
        <span class="redact-term__count">{group.marks.length}</span>
        <button class="btn btn--icon btn--sm" type="button" title={T.removeGroup} aria-label={T.removeGroup}
                onclick={(ev) => { ev.stopPropagation(); marks.remove(group.marks); }}>
          <Icon name="x" size={14} />
        </button>
      </div>
    {:else}
      <p class="redact-terms__empty muted">{T.empty}</p>
    {/each}
  </div>
  <div class="redact-panel__row">
    <span class="caption">{T.color}</span>
    {#each T.colors as [color, name] (color)}
      <button class="redact-swatch" class:is-checked={color === redact?.color} type="button" title={T.colorName(name)}
              aria-label={T.colorName(name)} style:--swatch={color} onclick={() => setColor(color)}></button>
    {/each}
  </div>
  <button class="btn btn--danger btn--lg btn--block" type="button" onclick={apply}><Icon name="scissors" />{T.apply}</button>
</div>
