<!-- Panel emergente abierto con openPopover() (ver popover.svelte.ts): bajo su botón o, si no cabe,
     encima; siempre dentro de la ventana. -->
<script lang="ts">
  import { closePopover, popover } from '../popover.svelte.ts';

  let el = $state<HTMLDivElement>();
  const GAP = 6;

  function place() {
    if (!el || !popover.anchor) return;
    const box = popover.anchor.getBoundingClientRect();
    const { width, height } = el.getBoundingClientRect();
    const left = Math.max(8, Math.min(box.left + box.width / 2 - width / 2, innerWidth - width - 8));
    let top = box.bottom + GAP;
    if (top + height > innerHeight - 8) top = Math.max(8, box.top - GAP - height);
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }

  // Se coloca al abrirse y cuando cambia su contenido (p. ej. al desplegar «Personalizado»).
  $effect(() => {
    if (!el || !popover.component) return;
    place();
    const resize = new ResizeObserver(place);
    resize.observe(el);
    return () => resize.disconnect();
  });

  // Se escucha tras el clic que lo abrió. Un clic en su botón lo deja a openPopover (que lo cierra).
  $effect(() => {
    if (!popover.component) return;
    const onOutside = (ev: PointerEvent) => {
      const target = ev.target as Node;
      if (el?.contains(target) || popover.anchor?.contains(target)) return;
      closePopover();
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      ev.stopPropagation(); // que Esc no quite también la selección del visor
      const anchor = popover.anchor as HTMLElement | null;
      closePopover();
      anchor?.focus();
    };
    const timer = setTimeout(() => {
      document.addEventListener('pointerdown', onOutside, true);
      document.addEventListener('keydown', onKey, true);
      window.addEventListener('resize', closePopover);
    });
    return () => {
      clearTimeout(timer);
      document.removeEventListener('pointerdown', onOutside, true);
      document.removeEventListener('keydown', onKey, true);
      window.removeEventListener('resize', closePopover);
    };
  });
</script>

{#if popover.component}
  <!-- Los clics dentro no llegan a la página (no quitan la selección de la anotación). -->
  <div class="popover" bind:this={el} role="dialog" tabindex="-1" onpointerdown={(ev) => ev.stopPropagation()}>
    <popover.component {...popover.props} />
  </div>
{/if}
