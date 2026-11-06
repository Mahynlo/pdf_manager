<!--
  Pantalla de carga de la versión de navegador, mientras arranca Python (unos segundos). La barra
  sigue los pasos reales del arranque: el evento `boot:progress` (lib/browser/worker.ts). En el
  escritorio no hace falta: la ventana se crea oculta hasta que la app está lista.
-->
<script lang="ts">
  import { on } from '$lib/api.ts';
  import { t } from '$texts';
  import logo from '../assets/logo.png';

  const T = t.shell.boot;

  let step = $state(0);
  let error = $state<string | null>(null);

  /** El arranque falló: se dice aquí, en vez de dejar la barra parada. */
  export function fail(message: string) {
    error = message;
  }

  $effect(() => on<number>('boot:progress', (value) => (step = value)));
</script>

<main class="splash" aria-busy={!error}>
  <img class="splash__logo" src={logo} alt="" width="96" height="96" />
  <h1 class="splash__title">{t.shell.header.appName}</h1>
  {#if error}
    <p class="splash__error" role="alert">{T.failed(error)}</p>
  {:else}
    <div class="splash__bar" role="progressbar" aria-label={T.steps[step]} aria-valuemin="0"
         aria-valuemax={T.steps.length} aria-valuenow={step + 1}>
      <span class="splash__fill" style:width="{((step + 1) / T.steps.length) * 100}%"></span>
    </div>
    <p class="splash__step">{T.steps[step]}</p>
    <p class="splash__note">{T.privacy}</p>
  {/if}
</main>
