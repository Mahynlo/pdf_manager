<!--
  Grosor del trazo o tamaño de letra (en un panel emergente, lib/popover.svelte.ts): valores
  rápidos, un deslizador y el número exacto, con una vista previa. Cada cambio se aplica al soltar
  el deslizador, al pulsar un valor o al confirmar el número (Intro o salir del campo): así cada
  uno es un solo paso de deshacer. El panel sigue abierto para afinar.

  El deslizador no es lineal: los valores pequeños, que son los que más se usan, tienen más recorrido.
-->
<script lang="ts">
  import { t } from '$texts';

  let { title, value, min, max, step, presets, preview, color, onPick }: {
    title: string;
    value: number;
    min: number;
    max: number;
    step: number;
    presets: number[];
    preview: 'line' | 'text';
    color: string;
    onPick: (value: number) => void;
  } = $props();

  const T = t.viewer.annotations.style;
  const SLIDER = 1000;
  const NUMBER = new Intl.NumberFormat('es', { maximumFractionDigits: 2 });

  // svelte-ignore state_referenced_locally
  let size = $state(value);
  // svelte-ignore state_referenced_locally
  let text = $state(NUMBER.format(value));

  const clamp = (n: number) => Math.min(max, Math.max(min, Math.round(n / step) * step));
  // Posición del deslizador (0…SLIDER) ↔ valor: cuadrática.
  const toValue = (pos: number) => clamp(min + (max - min) * (pos / SLIDER) ** 2);
  const toPos = (n: number) => Math.round(Math.sqrt((n - min) / (max - min)) * SLIDER);

  function set(n: number, apply = true) {
    size = clamp(n);
    text = NUMBER.format(size);
    if (apply && size !== value) {
      value = size;
      onPick(size);
    }
  }

  function typed() {
    const n = Number(text.replace(',', '.'));
    if (Number.isFinite(n) && n > 0) set(n);
    else text = NUMBER.format(size);
  }

  // Vista previa: tamaño real hasta lo que cabe.
  const shown = $derived(preview === 'line' ? Math.min(size, 44) : Math.min(size, 56));
</script>

<div class="size-panel">
  <p class="style-panel__title">{title}</p>

  <div class="size-panel__preview" aria-hidden="true" style:--swatch={color}>
    {#if preview === 'line'}
      <span class="size-panel__line" style:height="{Math.max(1, shown)}px"></span>
    {:else}
      <span class="size-panel__text" style:font-size="{shown}px">Aa</span>
    {/if}
  </div>

  <div class="size-panel__row">
    <input class="size-panel__slider" type="range" min="0" max={SLIDER} step="1" aria-label={title}
           aria-valuetext={T.points(NUMBER.format(size))}
           value={toPos(size)} oninput={(ev) => set(toValue(Number(ev.currentTarget.value)), false)}
           onchange={(ev) => set(toValue(Number(ev.currentTarget.value)))} />
    <label class="size-panel__number">
      <input class="input input--sm" type="text" inputmode="decimal" aria-label={title} title={T.sizeHint(min, max)}
             bind:value={text} onchange={typed} onkeydown={(ev) => ev.key === 'Enter' && typed()} />
      <span>pt</span>
    </label>
  </div>

  <div class="size-panel__presets" role="group">
    {#each presets as preset (preset)}
      <button class="btn btn--chip" class:is-checked={preset === size} type="button" aria-pressed={preset === size}
              onclick={() => set(preset)}>{NUMBER.format(preset)}</button>
    {/each}
  </div>
</div>
