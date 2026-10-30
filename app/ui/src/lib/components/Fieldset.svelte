<!-- Grupo con título (QGroupBox). -->
<script>
  let { legend, hidden = false, children } = $props();
</script>

<fieldset class="group" {hidden}>
  <legend>{legend}</legend>
  {@render children()}
</fieldset>
