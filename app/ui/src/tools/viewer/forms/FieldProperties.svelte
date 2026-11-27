<!--
  Propiedades del campo de formulario seleccionado, en el panel «Formularios» (FormsPanel.svelte), por
  secciones como en los editores de formularios:
    · Campo (todos): nombre (al salir del campo o con Enter; si es el de otro campo del mismo tipo,
      pregunta si unirlos), obligatorio, solo lectura y no exportar;
    · Texto: longitud máxima, multilínea, contraseña y un carácter por casilla;
    · Opciones (listas): una fila por opción (cambiarla, quitarla, añadir otra) y selección múltiple
      (lista) o permitir escribir (desplegable);
    · Botones (opción): que los del mismo valor se activen a la vez, los botones del grupo (ir a uno,
      quitarlo), añadir un botón y duplicar el grupo; en una casilla, su valor al marcarla;
    · Estilo: borde, relleno, grosor del borde y tamaño de letra; y eliminar.
  Cada cambio se aplica enseguida (fields.ts) y se deshace con Ctrl+Z, salvo el nombre y lo que cambia el
  motor de la app en los botones de acción y las firmas.
-->
<script lang="ts">
  import { PDF_FORM_FIELD_TYPE as K, type PdfWidgetAnnoObject } from '@embedpdf/models';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Icon from '$lib/Icon.svelte';
  import { t } from '$texts';
  import { NO_FILL, type ToolStyle } from '../annotations/styles.svelte.ts';
  import StyleButtons from '../style/StyleButtons.svelte';
  import {
    exportValueOf, hasFlag, hasText, kindOf, maxLenOf, optionsOf, type FlagName, type FormFields,
  } from './fields.ts';

  let { widget, fields }: { widget: PdfWidgetAnnoObject; fields: FormFields } = $props();
  const T = t.viewer.forms;
  const STYLED = new Set([K.TEXTFIELD, K.CHECKBOX, K.RADIOBUTTON, K.COMBOBOX, K.LISTBOX]);

  const type = $derived(widget.field.type);
  const kind = $derived(kindOf(type));
  const maxLen = $derived(maxLenOf(widget));
  const group = $derived(type === K.RADIOBUTTON ? fields.group(widget) : []);

  let name = $state('');
  let labels = $state<string[]>([]);
  $effect(() => {
    name = widget.field.name; // al cambiar de campo o tras cambiar el nombre
  });
  $effect(() => {
    labels = optionsOf(widget.field);
  });

  const style = $derived<Partial<ToolStyle>>({
    color: widget.strokeColor ?? '#000000',
    fill: widget.color ?? NO_FILL,
    width: widget.strokeWidth ?? 1,
    ...(hasText(widget.field) && { fontSize: widget.fontSize ?? 12 }),
  });

  const flag = (key: FlagName) => (ev: Event & { currentTarget: HTMLInputElement }) => void fields.setFlag(widget, key, ev.currentTarget.checked);

  /**
   * Enter aplica el nombre (al salir del campo). Sin `preventDefault`, la misma pulsación llegaba al
   * botón «Unir» de la pregunta que se abre si el nombre ya existe, y los unía sin preguntar.
   */
  function enterBlurs(ev: KeyboardEvent & { currentTarget: HTMLInputElement }) {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    ev.currentTarget.blur();
  }

  function applyName() {
    if (name.trim() && name.trim() !== widget.field.name) void fields.rename(widget, name);
    else name = widget.field.name;
  }

  function applyMaxLen(ev: Event & { currentTarget: HTMLInputElement }) {
    const value = Number(ev.currentTarget.value);
    fields.setMaxLen(widget, ev.currentTarget.value.trim() && value > 0 ? value : null);
  }

  function setOption(i: number, label: string) {
    fields.setOptions(widget, labels.map((old, k) => (k === i ? label : old)));
  }

  function addOption() {
    fields.setOptions(widget, [...labels, T.newOption(labels.length + 1)]);
  }

  function removeOption(i: number) {
    fields.setOptions(widget, labels.filter((_, k) => k !== i));
  }

  function restyle(patch: Partial<ToolStyle>) {
    const map: Record<string, unknown> = {};
    if (patch.color) map.strokeColor = patch.color;
    if (patch.fill) map.color = patch.fill;
    if (patch.width != null) map.strokeWidth = patch.width;
    if (patch.fontSize != null) map.fontSize = patch.fontSize;
    fields.restyle(widget, map);
  }
</script>

<!-- El texto primero: en `{@render x('…')}` un primer argumento literal es un icono (lo comprueba
     test_every_icon_used_in_the_frontend_exists). Sin parámetros opcionales con `?`: Svelte 5.51 los
     compila mal en los snippets (`tip? = …`). -->
{#snippet check(label: string, key: FlagName, tip = '', disabled = false)}
  <span class="forms-props__check" class:is-disabled={disabled}>
    <Checkbox {label} title={tip || undefined} checked={hasFlag(widget, key)} onchange={flag(key)} />
  </span>
{/snippet}

<section class="forms-props" aria-label={T.properties}>
  <div class="forms-panel__row">
    <Icon name={kind[1]} />
    <h3 class="heading">{T.properties}</h3>
    <span class="grow"></span>
    <span class="caption">{kind[0]} · {T.page(widget.pageIndex + 1)}</span>
  </div>

  <h4 class="forms-props__section">{T.section.field}</h4>
  <label class="field">
    <span class="caption">{T.name}</span>
    <input bind:value={name} class="input" type="text" aria-label={T.name} onchange={applyName} onkeydown={enterBlurs} />
  </label>
  <p class="forms-props__hint">{T.nameHint}</p>
  <div class="forms-props__checks">
    {@render check(T.required, 'required', T.requiredTip)}
    {@render check(T.readOnly, 'readOnly', T.readOnlyTip)}
    {@render check(T.noExport, 'noExport', T.noExportTip)}
  </div>

  {#if type === K.TEXTFIELD}
    <h4 class="forms-props__section">{T.section.text}</h4>
    <label class="forms-props__inline">
      <span class="caption">{T.maxLen}</span>
      <input class="input forms-props__number" type="number" min="1" step="1" placeholder={T.noLimit}
             value={maxLen ?? ''} aria-label={T.maxLen} onchange={applyMaxLen} onkeydown={enterBlurs} />
    </label>
    <div class="forms-props__checks forms-props__checks--column">
      {@render check(T.multiline, 'multiline')}
      {@render check(T.password, 'password', T.passwordTip)}
      {@render check(T.comb, 'comb', T.combTip, !maxLen)}
    </div>
  {:else if type === K.COMBOBOX || type === K.LISTBOX}
    <h4 class="forms-props__section">{T.section.options}</h4>
    <div class="forms-options" role="group" aria-label={T.section.options}>
      {#each labels as label, i (i)}
        <div class="forms-options__row">
          <input class="input" type="text" value={label} aria-label={T.option(i + 1)}
                 onchange={(ev) => setOption(i, ev.currentTarget.value)} onkeydown={enterBlurs} />
          <button class="btn btn--icon btn--sm is-danger" type="button" title={T.removeOption} aria-label={T.removeOption}
                  disabled={labels.length < 2} onclick={() => removeOption(i)}><Icon name="x" size={14} /></button>
        </div>
      {/each}
    </div>
    <div class="forms-props__actions">
      <button class="btn btn--sm" type="button" onclick={addOption}><Icon name="plus" size={14} />{T.addOption}</button>
    </div>
    {#if type === K.LISTBOX}
      {@render check(T.multiSelect, 'multiSelect')}
    {:else}
      {@render check(T.allowEdit, 'edit', T.allowEditTip)}
    {/if}
  {:else if type === K.RADIOBUTTON}
    <h4 class="forms-props__section">{T.section.buttons}</h4>
    <div class="forms-props__checks forms-props__checks--column">
      {@render check(T.unison, 'unison')}
      <span class="forms-props__check is-disabled"><Checkbox label={T.keepOne} title={T.keepOneTip} checked={true} /></span>
    </div>
    <div class="forms-options" role="group" aria-label={T.section.buttons}>
      {#each group as button, i (button.id)}
        <div class="forms-options__row" class:is-current={button.id === widget.id}>
          <button class="forms-options__button" type="button" title={T.buttonValue(exportValueOf(button))}
                  onclick={() => fields.goTo(button, true)}>
            <Icon name="circle-dot" size={14} />
            <span class="grow">{T.button(i + 1)}</span>
            <span class="caption">{T.page(button.pageIndex + 1)}</span>
          </button>
          <button class="btn btn--icon btn--sm is-danger" type="button" title={T.removeButton} aria-label={T.removeButton}
                  disabled={group.length < 2} onclick={() => fields.remove(button)}><Icon name="x" size={14} /></button>
        </div>
      {/each}
    </div>
    <div class="forms-props__actions">
      <button class="btn btn--sm" type="button" title={T.addButtonTip} onclick={() => fields.addButton(widget)}>
        <Icon name="plus" size={14} />{T.addButton}
      </button>
      <button class="btn btn--sm" type="button" title={T.duplicateGroupTip} onclick={() => fields.duplicateGroup(widget)}>
        <Icon name="copy" size={14} />{T.duplicateGroup}
      </button>
    </div>
  {:else if type === K.CHECKBOX && exportValueOf(widget)}
    <p class="forms-props__hint">{T.checkboxValue(exportValueOf(widget))}</p>
  {/if}

  {#if STYLED.has(type)}
    <h4 class="forms-props__section">{T.section.style}</h4>
    <div class="tb-style"><StyleButtons {style} colorTitle={T.border} onChange={restyle} /></div>
  {/if}
  <button class="btn btn--sm is-danger forms-props__remove" type="button" onclick={() => fields.remove(widget)}>
    <Icon name="trash" size={14} />{T.remove}
  </button>
</section>
