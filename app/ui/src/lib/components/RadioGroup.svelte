<!-- Opciones excluyentes (QRadioButton). `options`: [{ value, label }]. -->
<script lang="ts">
  let { options, value = $bindable(), onchange }: {
    options: { value: string; label: string }[];
    value?: string;
    onchange?: (ev: Event) => void;
  } = $props();
  const name = `radio-${Math.random().toString(36).slice(2)}`;
</script>

<div class="radio-group" role="radiogroup">
  {#each options as option (option.value)}
    <label class="check">
      <input type="radio" {name} value={option.value} bind:group={value} {onchange} />
      <span>{option.label}</span>
    </label>
  {/each}
</div>
