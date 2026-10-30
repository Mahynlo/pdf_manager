<!-- Pantalla de Inicio: archivos recientes a la izquierda y tarjetas de herramientas al centro. -->
<script>
  import RecentFiles from './RecentFiles.svelte';
  import { shell } from './shell.svelte.js';
  import { homeCards } from './tools.js';

  const cards = homeCards();
</script>

<div class="home">
  <RecentFiles />
  <div class="home__center">
    <span class="home__emoji" aria-hidden="true">📑</span>
    <h1 class="home__title">¿Qué quieres hacer hoy?</h1>
    <p class="home__lead">Selecciona una herramienta para comenzar a trabajar</p>
    <div class="home__cards">
      {#each cards as item (item.card.title)}
        <button class="card home-card" type="button"
                onclick={() => (item.tool ? shell.open(item.tool) : shell.openPdfDialog())}>
          <span class="home-card__icon" style:--c={item.color} aria-hidden="true">{item.emoji}</span>
          <span class="home-card__title">{item.card.title}</span>
          <span class="home-card__text">{item.card.text}</span>
        </button>
      {/each}
    </div>
  </div>
</div>
