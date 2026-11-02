<!-- Paso 3 de Extraer: documentos objetivo, carpeta de destino y forma de salida. -->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import RadioGroup from '$lib/components/RadioGroup.svelte';
  import Icon from '$lib/Icon.svelte';
  import { t } from '$texts';
  import type { ExtractJob } from './types.ts';

  const T = t.extract.targets;

  /** `output`: 'single' | 'split' (enlazable); `onState(job)` recibe el estado tras cada cambio. */
  let { job, onState, output = $bindable('single') }: {
    job: ExtractJob;
    onState: (job: ExtractJob) => void;
    output?: string;
  } = $props();

  const update = (method: string) => async () => onState(await call<ExtractJob>(method));
</script>

<div class="row">
  <h3 class="section-title grow">{T.title}</h3>
  <span class="caption">{T.count(job.targets.length)}</span>
</div>
<div class="row">
  <button class="btn" type="button" onclick={update('extract.pick_targets')}><Icon name="file-plus" />{T.load}</button>
  <button class="btn" type="button" onclick={update('extract.pick_target_folder')}><Icon name="folder-plus" />{T.addFolder}</button>
  <button class="btn" type="button" onclick={update('extract.clear_targets')}><Icon name="eraser" />{T.clear}</button>
</div>
<ul class="target-list" title={T.listTip}>
  {#each job.targets as target (target.path)}
    <li title={target.path}><Icon name="file-text" size={14} /><span class="ellipsis">{target.name}</span></li>
  {/each}
</ul>
<div class="row">
  <span class="muted ellipsis grow" title={job.destination.path}>{T.destination(job.destination.name)}</span>
  <button class="btn btn--sm" type="button" onclick={update('extract.choose_destination')}>{T.changeFolder}</button>
  <button class="btn btn--sm" type="button" onclick={() => call('extract.open_destination')}>
    <Icon name="folder-open" />{T.openFolder}
  </button>
</div>
<RadioGroup bind:value={output} options={[
  { value: 'single', label: T.single },
  { value: 'split', label: T.split },
]} />
