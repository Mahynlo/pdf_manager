<!--
  <dialog> modal que se abre al montarse (como QDialog.exec). Con Esc o close() se
  cierra y avisa con `onclose`. Se usa a través de openModal() (ver dialogs.svelte.ts).

    <Dialog bind:this={dialog} class="confirm" {onclose}> … </Dialog>
    dialog.close();
-->
<script lang="ts">
  import type { Snippet } from 'svelte';

  let { class: className = '', onclose, onkeydown, children }: {
    class?: string;
    onclose?: () => void;
    onkeydown?: (ev: KeyboardEvent) => void;
    children: Snippet;
  } = $props();
  let el: HTMLDialogElement;

  $effect(() => {
    el.showModal();
  });

  export function close() {
    if (el.open) el.close();
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<dialog bind:this={el} class="dialog {className}" {onclose} {onkeydown}>
  <div class="dialog__body">
    {@render children()}
  </div>
</dialog>
