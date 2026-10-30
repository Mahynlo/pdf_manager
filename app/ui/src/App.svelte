<!--
  Ventana principal: cabecera (marca, pestañas, acciones), una vista por pestaña,
  barra de estado, avisos y menú emergente. El estado de las pestañas vive en
  shell/shell.svelte.js.
-->
<script>
  import Menu from '$lib/components/Menu.svelte';
  import { feedback } from '$lib/feedback.svelte.js';
  import Icon from '$lib/Icon.svelte';
  import { openMenu, openMenuAt } from '$lib/menu.svelte.js';
  import { theme } from '$lib/theme.svelte.js';
  import { enableFileDrop } from './shell/dropzone.js';
  import Home from './shell/Home.svelte';
  import { HOME, shell } from './shell/shell.svelte.js';

  const TOAST_ICONS = { info: 'info', success: 'circle-check', danger: 'circle-alert', warning: 'circle-alert' };

  shell.start(theme.toggle);
  enableFileDrop();

  function tabKey(ev, key) {
    if (ev.key === 'Enter' || ev.key === ' ') shell.activate(key);
  }

  function tabContextMenu(ev, tab) {
    ev.preventDefault();
    if (tab.closable) openMenuAt(ev.clientX, ev.clientY, shell.tabContextMenu(tab.key));
  }
</script>

<svelte:document onkeydown={(ev) => shell.onKey(ev)} />

<header class="app-header">
  <button class="brand" type="button" title="Menú de la aplicación"
          onclick={(ev) => openMenu(ev.currentTarget, shell.brandMenu())}>
    <Icon name="file-text" size={18} />Extraer PDFs
  </button>
  <div class="tabbar" role="tablist" aria-label="Pestañas abiertas">
    {#each shell.tabs as tab (tab.key)}
      <div class="tab" class:is-closable={tab.closable} class:is-active={tab.key === shell.current}
           role="tab" tabindex="0" aria-selected={tab.key === shell.current} title={tab.path}
           onclick={() => shell.activate(tab.key)} onkeydown={(ev) => tabKey(ev, tab.key)}
           onauxclick={(ev) => ev.button === 1 && shell.close(tab.key)} oncontextmenu={(ev) => tabContextMenu(ev, tab)}>
        <Icon name={tab.icon} />
        <span class="ellipsis">{tab.label}</span>
        {#if tab.closable}
          <button class="tab__close" type="button" title="Cerrar pestaña (Ctrl+F4)"
                  onclick={(ev) => { ev.stopPropagation(); shell.close(tab.key); }}>
            <Icon name="x" size={14} />
          </button>
        {/if}
      </div>
    {/each}
  </div>
  <button class="btn btn--icon header-btn" type="button" title="Abrir documento PDF (Ctrl+O)"
          onclick={() => shell.openPdfDialog()}>
    <Icon name="plus" size={18} />
  </button>
  <div class="header-actions">
    <button class="btn btn--icon header-btn" type="button" title="Lista de pestañas abiertas"
            onclick={(ev) => openMenu(ev.currentTarget, shell.tabsMenu())}>
      <Icon name="list" size={18} />
    </button>
    <button class="btn btn--icon header-btn" type="button" title="Cambiar tema claro / oscuro" onclick={theme.toggle}>
      <Icon name={theme.dark ? 'sun' : 'moon'} size={18} />
    </button>
  </div>
</header>

<main class="views">
  {#each shell.tabs as tab (tab.key)}
    <section class="view" class:view--viewer={tab.viewer} role="tabpanel" hidden={tab.key !== shell.current}>
      {#if tab.key === HOME}
        <Home />
      {:else if tab.component}
        <tab.component bind:this={tab.instance} {...tab.props} />
      {/if}
    </section>
  {/each}
</main>

<footer class="statusbar">{feedback.status}</footer>

<div class="toasts" aria-live="polite">
  {#each feedback.toasts as t (t.id)}
    <div class="toast toast--{t.tone}" role="status">
      <Icon name={TOAST_ICONS[t.tone]} size={18} /><span>{t.message}</span>
    </div>
  {/each}
</div>

<Menu />
