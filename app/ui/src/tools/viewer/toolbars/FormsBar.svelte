<!--
  Barra «Formularios» (se abre con su botón en la barra superior, aparte de «Anotar»):
    · el modo: Rellenar (los campos se escriben) o Editar campos (se seleccionan, mueven y cambian);
    · crear campo: texto, casilla, botón de opción, lista desplegable y lista (plugin-form), y
      «Crear varios seguidos» (forms/state.svelte.ts);
    · campo anterior y siguiente (orden de tabulación del documento), para rellenar;
    · el panel de formularios: lista de campos, propiedades y datos (forms/FormsPanel.svelte).
  Si no cabe, se desplaza (lib/strip.ts).
-->
<script lang="ts" module>
  import { TOOLS } from '../canvas/canvas.ts';

  /** Las herramientas de crear campos, en el orden de la barra y del panel. */
  export const FIELD_TOOLS = [
    { key: TOOLS.FORM_TEXT, icon: 'text-cursor-input', kind: 'text' },
    { key: TOOLS.FORM_CHECKBOX, icon: 'square-check', kind: 'checkbox' },
    { key: TOOLS.FORM_RADIO, icon: 'circle-dot', kind: 'radio' },
    { key: TOOLS.FORM_COMBO, icon: 'square-chevron-down', kind: 'combo' },
    { key: TOOLS.FORM_LIST, icon: 'list-checks', kind: 'list' },
  ] as const;
</script>

<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { strip } from '$lib/strip.ts';
  import { t } from '$texts';
  import { FORM_DESIGN_TOOLS } from '../canvas/canvas.ts';
  import type { FormFields } from '../forms/fields.ts';
  import { formOptions } from '../forms/state.svelte.ts';

  /** `fillTool`: la herramienta con la que se rellena (la de texto, o la mano en pantallas táctiles). */
  let { tool, setTool, fillTool, visible, fields, panelOpen, togglePanel }: {
    tool: string;
    setTool: (tool: string) => void;
    fillTool: string;
    visible: boolean;
    fields: FormFields;
    panelOpen: boolean;
    togglePanel: () => void;
  } = $props();

  const T = t.viewer.forms;
  const editing = $derived(FORM_DESIGN_TOOLS.has(tool));
</script>

<!-- `keepFocus`: el botón no se lleva el foco (anterior/siguiente: el campo que se rellena lo conserva;
     si lo perdiera, el complemento olvidaría cuál es el actual). -->
{#snippet button(icon: string, title: string, onclick: () => void,
                 { checked = undefined, disabled = false, keepFocus = false }: { checked?: boolean; disabled?: boolean; keepFocus?: boolean } = {})}
  <button class="btn btn--icon tb-btn" class:is-checked={checked} type="button" {title} aria-label={title}
          aria-pressed={checked} {disabled} {onclick} onmousedown={(ev) => keepFocus && ev.preventDefault()}>
    <Icon name={icon} size={18} />
  </button>
{/snippet}

<div class="viewer-toolbar viewer-toolbar--forms" role="toolbar" aria-label={T.barLabel} hidden={!visible} use:strip>
  <div class="segmented forms-mode" role="group" aria-label={T.mode}>
    <button class="segmented__item" class:is-checked={!editing} type="button" title={T.fillTip} aria-pressed={!editing}
            onclick={() => setTool(fillTool)}><Icon name="text-cursor" size={15} />{T.fill}</button>
    <button class="segmented__item" class:is-checked={editing} type="button" title={T.editTip} aria-pressed={editing}
            onclick={() => setTool(TOOLS.POINTER)}><Icon name="pointer" size={15} />{T.edit}</button>
  </div>
  <span class="tb-sep" aria-hidden="true"></span>
  <div class="tb-group" role="group" aria-label={T.create}>
    {#each FIELD_TOOLS as { key, icon, kind } (key)}
      {@render button(icon, T.tools[kind], () => setTool(key), { checked: tool === key })}
    {/each}
    {@render button('repeat', T.keepToolTip, () => (formOptions.keepTool = !formOptions.keepTool), { checked: formOptions.keepTool })}
  </div>
  <span class="tb-sep" aria-hidden="true"></span>
  {@render button('chevron-up', T.prev, () => fields.step(false), { disabled: editing, keepFocus: true })}
  {@render button('chevron-down', T.next, () => fields.step(true), { disabled: editing, keepFocus: true })}
  <span class="tb-sep" aria-hidden="true"></span>
  {@render button('sliders-horizontal', T.panel, togglePanel, { checked: panelOpen })}
</div>
