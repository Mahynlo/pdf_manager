<!--
  Herramienta Seguridad: pestañas «Desbloquear» y «Proteger». Sin estado en el
  backend: cada pestaña guarda la ruta del archivo elegido.
-->
<script>
  import SubTabs from '$lib/components/SubTabs.svelte';
  import ToolHeader from '$lib/components/ToolHeader.svelte';
  import Protect from './Protect.svelte';
  import Unlock from './Unlock.svelte';

  let { tool } = $props();
</script>

{#snippet unlock()}<Unlock />{/snippet}
{#snippet protect()}<Protect />{/snippet}

<div class="tool-page">
  <ToolHeader emoji={tool.emoji} color={tool.color} title="Gestión de Seguridad de PDFs"
              subtitle="Desbloquea archivos encriptados y protege tus documentos confidenciales" />
  <hr class="divider" />
  <SubTabs tabs={[
    { label: 'Desbloquear', icon: 'lock-open', panel: unlock },
    { label: 'Proteger', icon: 'lock', panel: protect },
  ]} />
</div>
