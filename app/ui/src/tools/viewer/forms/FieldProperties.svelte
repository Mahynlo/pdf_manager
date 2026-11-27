<!--
  Propiedades del campo de formulario seleccionado, en el panel «Formularios» (FormsPanel.svelte):
  nombre (se aplica al salir del campo o con Enter; si es el de otro campo del mismo tipo, pregunta si
  unirlos), obligatorio, solo lectura, varias líneas (texto), opciones (listas), estilo y eliminar.
  Cada cambio se aplica enseguida (fields.ts `apply`/`restyle`) y se deshace con Ctrl+Z, salvo el nombre.
-->
<script lang="ts">
  import { PDF_FORM_FIELD_TYPE as K, type PdfWidgetAnnoObject } from '@embedpdf/models';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Icon from '$lib/Icon.svelte';
  import { t } from '$texts';
  import { NO_FILL, type ToolStyle } from '../annotations/styles.svelte.ts';
  import StyleButtons from '../style/StyleButtons.svelte';
  import { fieldProps, hasText, kindOf, type FieldProps, type FormFields } from './fields.ts';

  let { widget, fields }: { widget: PdfWidgetAnnoObject; fields: FormFields } = $props();
  const T = t.viewer.forms;

  const current = $derived(fieldProps(widget));
  const kind = $derived(kindOf(widget.field.type));
  let name = $state('');
  let optionsText = $state('');
  let error = $state('');
  $effect(() => {
    name = current.name; // al cambiar de campo o tras aplicar el nombre
  });
  $effect(() => {
    optionsText = current.options?.join('\n') ?? '';
  });
  const options = $derived(optionsText.split('\n').map((line) => line.trim()).filter(Boolean));
  const optionsChanged = $derived(current.options != null && JSON.stringify(options) !== JSON.stringify(current.options));

  const style = $derived<Partial<ToolStyle>>({
    color: widget.strokeColor ?? '#000000',
    fill: widget.color ?? NO_FILL,
    width: widget.strokeWidth ?? 1,
    ...(hasText(widget.field) && { fontSize: widget.fontSize ?? 12 }),
  });

  function apply(patch: Partial<FieldProps>) {
    error = '';
    void fields.apply(widget, { ...current, ...patch });
  }

  function applyName() {
    if (name.trim() && name.trim() !== current.name) apply({ name: name.trim() });
    else name = current.name;
  }

  /**
   * Enter aplica el nombre (al salir del campo). Sin `preventDefault`, la misma pulsación llegaba al
   * botón «Unir» de la pregunta que se abre si el nombre ya existe, y los unía sin preguntar.
   */
  function nameKey(ev: KeyboardEvent & { currentTarget: HTMLInputElement }) {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    ev.currentTarget.blur();
  }

  function applyOptions() {
    if (!options.length) {
      error = T.emptyOptions;
      return;
    }
    apply({ options });
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

<section class="forms-props" aria-label={T.properties}>
  <div class="forms-panel__row">
    <Icon name={kind[1]} />
    <h3 class="heading">{T.properties}</h3>
    <span class="grow"></span>
    <span class="caption">{kind[0]} · {T.page(widget.pageIndex + 1)}</span>
  </div>
  <label class="field">
    <span class="caption">{T.name}</span>
    <input bind:value={name} class="input" type="text" aria-label={T.name} onchange={applyName} onkeydown={nameKey} />
  </label>
  <p class="forms-props__hint">{T.nameHint}</p>
  <div class="forms-props__checks">
    <Checkbox label={T.required} checked={current.required} onchange={(ev) => apply({ required: ev.currentTarget.checked })} />
    <Checkbox label={T.readOnly} checked={current.readOnly} onchange={(ev) => apply({ readOnly: ev.currentTarget.checked })} />
    {#if widget.field.type === K.TEXTFIELD}
      <Checkbox label={T.multiline} checked={current.multiline} onchange={(ev) => apply({ multiline: ev.currentTarget.checked })} />
    {/if}
  </div>
  {#if current.options}
    <label class="field">
      <span class="caption">{T.options}</span>
      <textarea bind:value={optionsText} class="input dialog__textarea" rows="4" aria-label={T.options}></textarea>
    </label>
    <button class="btn btn--sm" type="button" disabled={!optionsChanged} onclick={applyOptions}>
      <Icon name="check" size={14} />{T.applyOptions}
    </button>
  {/if}
  {#if error}<p class="forms-props__error" role="alert">{error}</p>{/if}
  <div class="forms-panel__row">
    <span class="caption">{T.style}</span>
    <div class="tb-style"><StyleButtons {style} colorTitle={T.border} onChange={restyle} /></div>
  </div>
  <button class="btn btn--sm is-danger" type="button" onclick={() => fields.remove(widget)}>
    <Icon name="trash" size={14} />{T.remove}
  </button>
</section>
