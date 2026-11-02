<!-- Grupo con título (QGroupBox). -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let { legend, hidden = false, children }: { legend: string; hidden?: boolean; children: Snippet } = $props();
</script>

<fieldset class="group" {hidden}>
  <legend>{legend}</legend>
  {@render children()}
</fieldset>
