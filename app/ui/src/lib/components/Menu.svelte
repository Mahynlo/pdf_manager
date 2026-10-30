<!-- Menú emergente abierto con openMenu()/openMenuAt() (ver menu.svelte.js). -->
<script>
  import Icon from '../Icon.svelte';
  import { closeMenu, menu } from '../menu.svelte.js';

  let el = $state();

  // Lo mantiene dentro de la ventana y enfoca la primera opción.
  $effect(() => {
    if (!el || !menu.items) return;
    const { width, height } = el.getBoundingClientRect();
    let left = Math.min(menu.x, innerWidth - width - 4);
    if (menu.anchor && menu.x + width > innerWidth - 4) left = menu.anchor.right - width;
    el.style.left = `${Math.max(4, left)}px`;
    el.style.top = `${Math.max(4, Math.min(menu.y, innerHeight - height - 4))}px`;
    el.querySelector('.menu__item:not(:disabled)')?.focus();
  });

  // Se escucha tras el clic que abrió el menú, para no cerrarlo en el acto.
  $effect(() => {
    if (!menu.items) return;
    const onOutside = (ev) => el && !el.contains(ev.target) && closeMenu();
    const onKey = (ev) => {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      closeMenu();
    };
    const timer = setTimeout(() => {
      document.addEventListener('pointerdown', onOutside, true);
      document.addEventListener('keydown', onKey, true);
      window.addEventListener('blur', closeMenu);
    });
    return () => {
      clearTimeout(timer);
      document.removeEventListener('pointerdown', onOutside, true);
      document.removeEventListener('keydown', onKey, true);
      window.removeEventListener('blur', closeMenu);
    };
  });

  function select(item) {
    closeMenu();
    item.onSelect?.();
  }
</script>

{#if menu.items}
  <div class="menu" role="menu" bind:this={el}>
    {#each menu.items as item, i (i)}
      {#if item === 'separator'}
        <div class="menu__sep" role="separator"></div>
      {:else}
        <button class="menu__item" class:is-checked={item.checked} type="button" role="menuitem"
                disabled={Boolean(item.disabled)} onclick={() => select(item)}>
          {#if item.icon}<Icon name={item.icon} />{:else}<span class="menu__spacer"></span>{/if}
          <span class="ellipsis">{item.label}</span>
        </button>
      {/if}
    {/each}
  </div>
{/if}
