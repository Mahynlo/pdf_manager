<!--
  Ventana principal: cabecera (marca, pestañas, acciones), una vista por pestaña,
  barra de estado, avisos y menú emergente. El estado de las pestañas vive en
  shell/shell.svelte.ts.
-->
<script lang="ts">
  import Menu from '$lib/components/Menu.svelte';
  import { feedback } from '$lib/feedback.svelte.ts';
  import Icon from '$lib/Icon.svelte';
  import { openMenu, openMenuAt } from '$lib/menu.svelte.ts';
  import { theme } from '$lib/theme.svelte.ts';
  import { enableFileDrop } from './shell/dropzone.ts';
  import Home from './shell/Home.svelte';
  import { HOME, shell } from './shell/shell.svelte.ts';
  import type { Tone } from '$lib/ui.ts';
  import { t, tip } from '$texts';

  const T = t.shell.header;

  const TOAST_ICONS: Record<Tone, string> = { info: 'info', success: 'circle-check', danger: 'circle-alert', warning: 'circle-alert' };

  shell.start(theme.toggle);
  enableFileDrop();

  function tabKey(ev: KeyboardEvent, key: string) {
    if (ev.key === 'Enter' || ev.key === ' ') shell.activate(key);
  }

  function tabContextMenu(ev: MouseEvent, tab: { closable: boolean; key: string }) {
    ev.preventDefault();
    if (tab.closable) openMenuAt(ev.clientX, ev.clientY, shell.tabContextMenu(tab.key));
  }
</script>

<svelte:document onkeydown={(ev) => shell.onKey(ev)} />

<header class="app-header">
  <button class="brand" type="button" title={T.brandMenu}
          onclick={(ev) => openMenu(ev.currentTarget, shell.brandMenu())}>
    <Icon name="file-text" size={18} />{T.appName}
  </button>
  <div class="tabbar" role="tablist" aria-label={T.tabs}>
    {#each shell.tabs as tab (tab.key)}
      <div class="tab" class:is-closable={tab.closable} class:is-active={tab.key === shell.current}
           role="tab" tabindex="0" aria-selected={tab.key === shell.current} title={tab.path}
           onclick={() => shell.activate(tab.key)} onkeydown={(ev) => tabKey(ev, tab.key)}
           onauxclick={(ev) => ev.button === 1 && shell.close(tab.key)} oncontextmenu={(ev) => tabContextMenu(ev, tab)}>
        <Icon name={tab.icon} />
        <span class="ellipsis">{tab.label}</span>
        {#if tab.closable}
          <button class="tab__close" type="button" title={tip(T.closeTab)}
                  onclick={(ev) => { ev.stopPropagation(); shell.close(tab.key); }}>
            <Icon name="x" size={14} />
          </button>
        {/if}
      </div>
    {/each}
  </div>
  <button class="btn btn--icon header-btn" type="button" title={tip(T.openPdf)}
          onclick={() => shell.openPdfDialog()}>
    <Icon name="plus" size={18} />
  </button>
  <div class="header-actions">
    <button class="btn btn--icon header-btn" type="button" title={T.tabsList}
            onclick={(ev) => openMenu(ev.currentTarget, shell.tabsMenu())}>
      <Icon name="list" size={18} />
    </button>
    <button class="btn btn--icon header-btn" type="button" title={T.theme} onclick={theme.toggle}>
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
  {#each feedback.toasts as toast (toast.id)}
    <div class="toast toast--{toast.tone}" role="status">
      <Icon name={TOAST_ICONS[toast.tone]} size={18} /><span>{toast.message}</span>
    </div>
  {/each}
</div>

<Menu />
