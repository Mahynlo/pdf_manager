<!-- Casilla con texto. -->
<script>
  let { label, checked = $bindable(false), title, onchange } = $props();
</script>

<label class="check" {title}>
  <input type="checkbox" bind:checked {onchange} />
  <span>{label}</span>
</label>
