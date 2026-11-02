<!--
  Herramienta Seguridad: pestañas «Desbloquear» y «Proteger». Sin estado en el
  backend: cada pestaña guarda la ruta del archivo elegido.
-->
<script lang="ts">
  import SubTabs from '$lib/components/SubTabs.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import { t } from '$texts';
  import type { Tool } from '../../shell/tools.ts';
  import Protect from './Protect.svelte';
  import Unlock from './Unlock.svelte';

  const T = t.security;

  let { tool }: { tool: Tool } = $props();
</script>

{#snippet unlock()}<Unlock />{/snippet}
{#snippet protect()}<Protect />{/snippet}

<div class="tool-page">
  <ToolHeader emoji={tool.emoji} color={tool.color} title={T.title} subtitle={T.subtitle} />
  <hr class="divider" />
  <SubTabs tabs={[
    { label: T.tabs.unlock, icon: 'lock-open', panel: unlock },
    { label: T.tabs.protect, icon: 'lock', panel: protect },
  ]} />
</div>
