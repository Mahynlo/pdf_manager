<!--
  Panel «Formularios» del lateral derecho (con la barra «Formularios», toolbars/FormsBar.svelte):
    · el modo (Rellenar / Editar campos) y las herramientas para crear campos;
    · la lista de campos del documento, con filtro: tipo, nombre, página y si tiene valor; un clic
      lleva al campo (para escribir en él o, en «Editar campos», seleccionarlo);
    · las propiedades del campo seleccionado (FieldProperties.svelte);
    · los datos: exportar a un .json, importar y vaciar el formulario.
  Se vuelve a leer con cada cambio de las anotaciones o de un valor (annotations.ts `watch`).
-->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Icon from '$lib/Icon.svelte';
  import { t } from '$texts';
  import type { Annotations } from '../annotations/annotations.ts';
  import { FORM_DESIGN_TOOLS, TOOLS } from '../canvas/canvas.ts';
  import { FIELD_TOOLS } from '../toolbars/FormsBar.svelte';
  import FieldProperties from './FieldProperties.svelte';
  import { isFilled, kindOf, type FieldEntry, type FormFields } from './fields.ts';
  import { formOptions } from './state.svelte.ts';

  let { fields, annotations, tool, setTool, fillTool, close }: {
    fields: FormFields;
    annotations: Annotations;
    tool: string;
    setTool: (tool: string) => void;
    fillTool: string;
    close: () => void;
  } = $props();

  const T = t.viewer.forms;
  let version = $state(0); // sube con cada cambio: la lista y la selección se vuelven a leer
  let filter = $state('');
  let picker: HTMLInputElement;
  // svelte-ignore state_referenced_locally
  onDestroy(annotations.watch(() => version++));

  const editing = $derived(FORM_DESIGN_TOOLS.has(tool));
  const entries = $derived.by(() => {
    void version;
    return fields.list();
  });
  const shown = $derived(entries.filter((entry) => entry.name.toLowerCase().includes(filter.trim().toLowerCase())));
  const filled = $derived(entries.filter(isFilled).length);
  const selected = $derived.by(() => {
    void version;
    const items = annotations.selected();
    return items.length === 1 ? fields.widget(items[0].id) : null;
  });

  const valueLabel = (entry: FieldEntry) => (isFilled(entry) ? (entry.value === 'Off' ? '' : entry.value) : '');

  async function importFile(ev: Event & { currentTarget: HTMLInputElement }) {
    const file = ev.currentTarget.files?.[0];
    ev.currentTarget.value = '';
    if (file) await fields.importData(await file.text());
  }
</script>

<div class="forms-panel">
  <div class="forms-panel__head">
    <span class="forms-panel__icon"><Icon name="text-cursor-input" size={20} /></span>
    <h2 class="heading">{T.title}</h2>
    <span class="grow"></span>
    <button class="btn btn--icon btn--sm" type="button" title={T.close} aria-label={T.close} onclick={close}><Icon name="x" /></button>
  </div>

  <div class="segmented forms-mode forms-mode--block" role="group" aria-label={T.mode}>
    <button class="segmented__item" class:is-checked={!editing} type="button" title={T.fillTip} aria-pressed={!editing}
            onclick={() => setTool(fillTool)}><Icon name="text-cursor" size={15} />{T.fill}</button>
    <button class="segmented__item" class:is-checked={editing} type="button" title={T.editTip} aria-pressed={editing}
            onclick={() => setTool(TOOLS.POINTER)}><Icon name="pointer" size={15} />{T.edit}</button>
  </div>

  <span class="caption">{T.create}</span>
  <div class="forms-create" role="group" aria-label={T.create}>
    {#each FIELD_TOOLS as { key, icon, kind } (key)}
      <button class="forms-create__tool" class:is-checked={tool === key} type="button" title={T.tools[kind]}
              aria-label={T.tools[kind]} aria-pressed={tool === key} onclick={() => setTool(key)}>
        <Icon name={icon} size={18} /><span>{T.types[kind]}</span>
      </button>
    {/each}
  </div>
  <Checkbox label={T.keepTool} title={T.keepToolTip} bind:checked={formOptions.keepTool} />

  <div class="forms-panel__row">
    <Icon name="list" /><h3 class="heading">{T.fields}</h3>
    <span class="grow"></span>
    {#if entries.length}<span class="caption">{T.summary(filled, entries.length)}</span>{/if}
  </div>
  {#if entries.length > 6}
    <input bind:value={filter} class="input" type="search" placeholder={T.filter} aria-label={T.filter} />
  {/if}
  <div class="forms-list" role="group" aria-label={T.fields}>
    {#each shown as entry (entry.name)}
      {@const [label, icon] = kindOf(entry.type)}
      {@const current = entry.widgets.some((widget) => widget.id === selected?.id)}
      <button class="forms-item" class:is-current={current} type="button" title={T.goTo(entry.name)}
              onclick={() => fields.goTo(entry.widgets[0], editing)}>
        <span class="forms-item__icon" title={label}><Icon name={icon} size={16} /></span>
        <span class="forms-item__text">
          <span class="forms-item__name">{entry.name}</span>
          {#if valueLabel(entry)}<span class="forms-item__value">{valueLabel(entry)}</span>{/if}
        </span>
        {#if entry.required}<span class="forms-item__badge" title={T.requiredBadge}>*</span>{/if}
        {#if entry.readOnly}<span class="forms-item__lock" title={T.readOnlyBadge}><Icon name="lock" size={13} /></span>{/if}
        <span class="forms-item__page">{T.page(entry.widgets[0].pageIndex + 1)}</span>
        <span class="forms-item__dot" class:is-filled={isFilled(entry)} aria-hidden="true"></span>
      </button>
    {:else}
      <p class="forms-list__empty muted">{entries.length ? T.noMatch : T.noFields}</p>
    {/each}
  </div>

  {#if selected}
    {#key selected.id}<FieldProperties widget={selected} {fields} />{/key}
  {:else}
    <p class="forms-panel__hint muted">{T.noSelection}</p>
  {/if}

  <div class="forms-panel__row"><Icon name="file-text" /><h3 class="heading">{T.data.title}</h3></div>
  <div class="forms-data">
    <button class="btn btn--sm" type="button" title={T.data.exportTip} disabled={!entries.length} onclick={() => fields.exportData()}>
      <Icon name="file-down" size={14} />{T.data.export}
    </button>
    <button class="btn btn--sm" type="button" title={T.data.importTip} disabled={!entries.length} onclick={() => picker.click()}>
      <Icon name="file-up" size={14} />{T.data.import}
    </button>
    <button class="btn btn--sm" type="button" disabled={!filled} onclick={() => fields.clear()}>
      <Icon name="eraser" size={14} />{T.data.clear}
    </button>
    <input bind:this={picker} type="file" accept=".json,application/json" hidden onchange={importFile} />
  </div>
</div>
