<!--
  Ventana principal: cabecera (marca, pestañas, acciones), una vista por pestaña,
  barra de estado, avisos y menú emergente. El estado de las pestañas vive en
  shell/shell.svelte.ts y la tira de pestañas en shell/TabStrip.svelte.
-->
<script lang="ts">
  import Menu from '$lib/components/Menu.svelte';
  import { feedback } from '$lib/feedback.svelte.ts';
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.ts';
  import { theme } from '$lib/theme.svelte.ts';
  import { enableFileDrop } from './shell/dropzone.ts';
  import Home from './shell/Home.svelte';
  import { guardNavigation } from './shell/navigation.ts';
  import { HOME, shell } from './shell/shell.svelte.ts';
  import TabStrip from './shell/TabStrip.svelte';
  import type { Tone } from '$lib/ui.ts';
  import { t, tip } from '$texts';

  const T = t.shell.header;

  const TOAST_ICONS: Record<Tone, string> = { info: 'info', success: 'circle-check', danger: 'circle-alert', warning: 'circle-alert' };

  shell.start(theme.toggle);
  enableFileDrop();
  guardNavigation();
</script>

<svelte:document onkeydown={(ev) => shell.onKey(ev)} />

<header class="app-header">
  <button class="brand" type="button" title={T.brandMenu}
          onclick={(ev) => openMenu(ev.currentTarget, shell.brandMenu())}>
    <Icon name="file-text" size={18} /><span class="brand__label">{T.appName}</span>
  </button>
  <TabStrip />
  <button class="btn btn--icon header-btn" type="button" title={tip(T.openPdf)}
          onclick={() => shell.openPdfDialog()}>
    <Icon name="plus" size={18} />
  </button>
  <div class="header-actions">
    <button class="btn btn--icon header-btn" type="button" title={T.tabsList}
            onclick={(ev) => openMenu(ev.currentTarget, shell.tabsMenu())}>
      <Icon name="list" size={18} />
    </button>
    <button class="btn btn--icon header-btn header-theme" type="button" title={T.theme} onclick={theme.toggle}>
      <Icon name={theme.dark ? 'sun' : 'moon'} size={18} />
    </button>
  </div>
</header>

<main class="views">
  {#each shell.views as tab (tab.key)}
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
