<!-- Paso 3 de Extraer: documentos objetivo, carpeta de destino y forma de salida. -->
<script>
  import { call } from '$lib/api.js';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import Icon from '$lib/Icon.svelte';

  /** `output`: 'single' | 'split' (enlazable); `onState(job)` recibe el estado tras cada cambio. */
  let { job, onState, output = $bindable('single') } = $props();

  const update = (method) => async () => onState(await call(method));
</script>

<div class="row">
  <h3 class="section-title grow">Paso 3: Documentos Objetivo y Destino</h3>
  <span class="caption">Archivos: {job.targets.length}</span>
</div>
<div class="row">
  <button class="btn" type="button" onclick={update('extract.pick_targets')}><Icon name="file-plus" />Cargar PDFs...</button>
  <button class="btn" type="button" onclick={update('extract.pick_target_folder')}><Icon name="folder-plus" />Añadir Carpeta...</button>
  <button class="btn" type="button" onclick={update('extract.clear_targets')}><Icon name="eraser" />Limpiar</button>
</div>
<ul class="target-list" title="Documentos que serán escaneados">
  {#each job.targets as t (t.path)}
    <li title={t.path}><Icon name="file-text" size={14} /><span class="ellipsis">{t.name}</span></li>
  {/each}
</ul>
<div class="row">
  <span class="muted ellipsis grow" title={job.destination.path}>Destino: {job.destination.name}</span>
  <button class="btn btn--sm" type="button" onclick={update('extract.choose_destination')}>Cambiar Carpeta...</button>
  <button class="btn btn--sm" type="button" onclick={() => call('extract.open_destination')}>
    <Icon name="folder-open" />Abrir Carpeta
  </button>
</div>
<RadioGroup bind:value={output} options={[
  { value: 'single', label: 'Combinar en un solo PDF' },
  { value: 'split', label: 'Archivos separados por PDF' },
]} />
