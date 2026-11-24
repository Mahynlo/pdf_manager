<!--
  Selector de color de una anotación (en un panel emergente, lib/popover.svelte.ts): los colores
  de la paleta y los recientes se aplican con un clic; «Personalizado» abre un editor (cuadro de
  saturación y brillo, barra de matiz, código y cuentagotas) que se aplica con «Aplicar».
  `allowNone`: con «Sin relleno» (el relleno de las formas).
-->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { closePopover } from '$lib/popover.svelte.ts';
  import { NO_FILL, PRESETS, rememberColor, styles } from '../annotations/styles.svelte.ts';
  import { hexToHsv, hsvToHex, isLight, normalizeHex, type Hsv } from './color.ts';
  import { t } from '$texts';

  let { title, value, allowNone = false, onPick }: {
    title: string;
    value: string;
    allowNone?: boolean;
    onPick: (color: string) => void;
  } = $props();

  const T = t.viewer.annotations.style;
  // El cuentagotas del sistema (Chromium/WebView2); sin él no se muestra el botón.
  const EyeDropperApi = (globalThis as { EyeDropper?: new () => { open(): Promise<{ sRGBHexColor: string }> } }).EyeDropper;

  const current = $derived(value === NO_FILL ? NO_FILL : normalizeHex(value) ?? '#000000');
  const known = $derived(current === NO_FILL || PRESETS.some(([c]) => c === current) || styles.recent.includes(current));

  // Editor personalizado: abierto de entrada si el color actual no está a la vista.
  // svelte-ignore state_referenced_locally
  let editing = $state(!known);
  // svelte-ignore state_referenced_locally
  let hsv = $state<Hsv>(hexToHsv(current === NO_FILL ? '#1565C0' : current));
  const hex = $derived(hsvToHex(hsv));
  let hexText = $state('');
  $effect(() => {
    hexText = hex;
  });

  let square = $state<HTMLDivElement>();

  function pick(color: string) {
    closePopover();
    onPick(color);
  }

  function apply() {
    rememberColor(hex);
    pick(hex);
  }

  // ── Cuadro de saturación (horizontal) y brillo (vertical) ─────────────────
  function fromPointer(ev: PointerEvent) {
    const box = square!.getBoundingClientRect();
    const s = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
    const v = 1 - Math.min(1, Math.max(0, (ev.clientY - box.top) / box.height));
    hsv = { ...hsv, s, v };
  }

  function squareDown(ev: PointerEvent) {
    square!.setPointerCapture(ev.pointerId);
    fromPointer(ev);
  }

  function squareKey(ev: KeyboardEvent) {
    const step = ev.shiftKey ? 0.1 : 0.01;
    const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    const move = moves[ev.key];
    if (!move) {
      if (ev.key === 'Enter') apply();
      return;
    }
    ev.preventDefault();
    hsv = { ...hsv, s: Math.min(1, Math.max(0, hsv.s + move[0])), v: Math.min(1, Math.max(0, hsv.v + move[1])) };
  }

  /** Mientras se escribe, solo el código completo (si no, «#ab» ya sería un color); al salir, también el corto. */
  function typed(done = false) {
    const color = done || /^#?[0-9a-f]{6}$/i.test(hexText.trim()) ? normalizeHex(hexText) : null;
    if (color) hsv = hexToHsv(color);
    else if (done) hexText = hex;
  }

  async function eyedrop() {
    try {
      const { sRGBHexColor } = await new EyeDropperApi!().open();
      const color = normalizeHex(sRGBHexColor);
      if (color) hsv = hexToHsv(color);
    } catch {
      // cancelado con Esc
    }
  }
</script>

{#snippet swatch(color: string, name: string)}
  <button class="color-panel__swatch" class:is-checked={color === current} class:is-light={isLight(color)} type="button"
          style:--swatch={color} title={name} aria-label={name} aria-pressed={color === current} onclick={() => pick(color)}>
    {#if color === current}<Icon name="check" size={14} />{/if}
  </button>
{/snippet}

<div class="color-panel">
  <p class="style-panel__title">{title}</p>

  {#if allowNone}
    <button class="color-panel__none" class:is-checked={current === NO_FILL} type="button" aria-pressed={current === NO_FILL}
            onclick={() => pick(NO_FILL)}>
      <span class="color-panel__none-swatch" aria-hidden="true"></span>{T.noFill}
      {#if current === NO_FILL}<Icon name="check" size={14} />{/if}
    </button>
  {/if}

  <div class="color-panel__grid" role="group" aria-label={T.presets}>
    {#each PRESETS as [color, name] (color)}{@render swatch(color, name)}{/each}
  </div>

  {#if styles.recent.length}
    <p class="style-panel__label">{T.recent}</p>
    <div class="color-panel__grid" role="group" aria-label={T.recent}>
      {#each styles.recent as color (color)}{@render swatch(color, color)}{/each}
    </div>
  {/if}

  <button class="color-panel__toggle" type="button" aria-expanded={editing} onclick={() => (editing = !editing)}>
    <Icon name="palette" size={16} />{T.custom}
    <span class="color-panel__chevron" class:is-open={editing}><Icon name="chevron-down" size={14} /></span>
  </button>

  {#if editing}
    <div class="color-panel__editor">
      <div class="color-panel__square" bind:this={square} style:--hue={hsv.h} role="slider" tabindex="0"
           aria-label={T.shade} aria-valuetext={hex} aria-valuenow={Math.round(hsv.s * 100)}
           onpointerdown={squareDown} onpointermove={(ev) => ev.buttons && fromPointer(ev)} onkeydown={squareKey}>
        <span class="color-panel__thumb" style:left="{hsv.s * 100}%" style:top="{(1 - hsv.v) * 100}%" style:--swatch={hex}></span>
      </div>
      <input class="color-panel__hue" type="range" min="0" max="359" step="1" aria-label={T.hue}
             value={Math.round(hsv.h)} oninput={(ev) => (hsv = { ...hsv, h: Number(ev.currentTarget.value) })} />
      <div class="color-panel__row">
        <span class="color-panel__compare" aria-hidden="true">
          <span style:--swatch={current === NO_FILL ? 'transparent' : current} title={T.current}></span>
          <span style:--swatch={hex} title={T.new}></span>
        </span>
        <input class="input input--sm color-panel__hex" type="text" maxlength="7" spellcheck="false" aria-label={T.hex}
               bind:value={hexText} oninput={() => typed()} onblur={() => typed(true)}
               onkeydown={(ev) => { if (ev.key === 'Enter' && normalizeHex(hexText)) { typed(true); apply(); } }} />
        {#if EyeDropperApi}
          <button class="btn btn--icon btn--sm" type="button" title={T.eyedropper} aria-label={T.eyedropper} onclick={eyedrop}>
            <Icon name="pipette" size={16} />
          </button>
        {/if}
      </div>
      <div class="color-panel__actions">
        <button class="btn btn--sm" type="button" onclick={() => closePopover()}>{T.cancel}</button>
        <button class="btn btn--primary btn--sm" type="button" onclick={apply}>{T.apply}</button>
      </div>
    </div>
  {/if}
</div>
