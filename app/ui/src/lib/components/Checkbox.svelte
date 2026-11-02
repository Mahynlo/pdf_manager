<!-- Casilla con texto. -->
<script lang="ts">
  let { label, checked = $bindable(false), title, onchange }: {
    label: string;
    checked?: boolean;
    title?: string;
    onchange?: (ev: Event & { currentTarget: HTMLInputElement }) => void;
  } = $props();
</script>

<label class="check" {title}>
  <input type="checkbox" bind:checked {onchange} />
  <span>{label}</span>
</label>
