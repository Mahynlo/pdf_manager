<!-- Pantalla de Inicio: archivos recientes a la izquierda; a la derecha, abrir un documento y las
     tarjetas de las herramientas. Soltar archivos funciona en toda la ventana (dropzone.ts): la zona
     de abrir solo lo indica. -->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import RecentFiles from './RecentFiles.svelte';
  import { shell } from './shell.svelte.ts';
  import { homeCards, type HomeCard } from './tools.ts';
  import { t } from '$texts';

  const T = t.shell.home;

  const cards = homeCards();

  function run(item: HomeCard) {
    if (item.tool) shell.open(item.tool);
    else if (item.action === 'images-to-pdf') shell.imagesToPdf();
    else shell.openPdfDialog();
  }
</script>

<div class="home">
  <RecentFiles />
  <div class="home__main">
    <div class="home__inner">
      <header class="home__head">
        <span class="home__local" title={T.localTip}><Icon name="shield-check" size={14} />{T.local}</span>
        <h1 class="home__title">{T.heading}</h1>
        <p class="home__lead">{T.lead}</p>
      </header>

      <section class="home-open" aria-labelledby="home-open-title">
        <span class="home-open__icon" aria-hidden="true"><Icon name="upload" size={24} /></span>
        <div class="home-open__info">
          <h2 class="home-open__title" id="home-open-title">
            {T.open.title}
            <span class="home-open__formats" aria-hidden="true">
              {#each T.open.formats as format (format)}<span class="home-open__format">.{format}</span>{/each}
            </span>
          </h2>
          <p class="home-open__text home-open__text--mouse">
            {T.open.text} <span class="keys"><kbd class="keycap">Ctrl</kbd>+<kbd class="keycap">O</kbd></span>
          </p>
          <p class="home-open__text home-open__text--touch">{T.open.touch}</p>
        </div>
        <button class="btn btn--primary btn--lg home-open__button" type="button" onclick={() => shell.openPdfDialog()}>
          <Icon name="folder-open" size={18} />{T.open.button}
        </button>
      </section>

      <h2 class="home__section">{T.tools}</h2>
      <div class="home__cards">
        {#each cards as item (item.card.title)}
          <button class="card home-card" type="button" style:--c={item.color} onclick={() => run(item)}>
            <span class="home-card__top">
              <span class="home-card__icon" aria-hidden="true"><Icon name={item.icon} size={22} /></span>
              <span class="home-card__go" aria-hidden="true"><Icon name="arrow-right" size={18} /></span>
            </span>
            <span class="home-card__title">{item.card.title}</span>
            <span class="home-card__text">{item.card.text}</span>
          </button>
        {/each}
      </div>
    </div>
  </div>
</div>
