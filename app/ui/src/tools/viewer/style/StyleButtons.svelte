<!--
  Botones de estilo de una anotación: color, grosor, relleno y tamaño de letra, solo los que
  tiene `style` (las propiedades que faltan no se muestran). Cada uno abre su panel. Están en la
  barra de anotaciones (estilo de la herramienta activa) y en la de la selección (editing.ts).
  `style` null: botón de color desactivado («elige una herramienta»).
-->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { openPopover } from '$lib/popover.svelte.ts';
  import { FONT_SIZE, NO_FILL, WIDTH, type ToolStyle } from '../annotations/styles.svelte.ts';
  import ColorPanel from './ColorPanel.svelte';
  import SizePanel from './SizePanel.svelte';
  import { t } from '$texts';

  let { style, colorTitle, onChange }: {
    style: Partial<ToolStyle> | null;
    colorTitle?: string; // «Color del texto» en el texto libre
    onChange: (patch: Partial<ToolStyle>) => void;
  } = $props();

  const T = t.viewer.annotations.style;
  const NUMBER = new Intl.NumberFormat('es', { maximumFractionDigits: 2 });
  const points = (n: number) => T.points(NUMBER.format(n));

  function color(ev: MouseEvent & { currentTarget: HTMLElement }) {
    openPopover(ev.currentTarget, ColorPanel, {
      title: colorTitle ?? T.color, value: style!.color!, onPick: (value: string) => onChange({ color: value }),
    });
  }

  function fill(ev: MouseEvent & { currentTarget: HTMLElement }) {
    openPopover(ev.currentTarget, ColorPanel, {
      title: T.fill, value: style!.fill!, allowNone: true, onPick: (value: string) => onChange({ fill: value }),
    });
  }

  function size(ev: MouseEvent & { currentTarget: HTMLElement }, kind: 'width' | 'fontSize') {
    const range = kind === 'width' ? WIDTH : FONT_SIZE;
    openPopover(ev.currentTarget, SizePanel, {
      ...range, title: kind === 'width' ? T.width : T.fontSize, value: style![kind]!, color: style!.color ?? '#000000',
      preview: kind === 'width' ? 'line' : 'text', onPick: (value: number) => onChange({ [kind]: value }),
    });
  }
</script>

{#if !style}
  <button class="btn btn--icon tb-btn style-btn" type="button" disabled title={T.noTool} aria-label={T.noTool}>
    <span class="style-btn__swatch style-btn__swatch--empty" aria-hidden="true"></span>
  </button>
{:else}
  {#if style.color != null}
    {@const title = colorTitle ?? T.color}
    <button class="btn btn--icon tb-btn style-btn" type="button" {title} aria-label={title} aria-haspopup="dialog" onclick={color}>
      <span class="style-btn__swatch" style:--swatch={style.color} aria-hidden="true"></span>
      <Icon name="chevron-down" size={12} />
    </button>
  {/if}
  {#if style.width != null}
    <button class="btn btn--icon tb-btn style-btn style-btn--value" type="button" title={T.width} aria-label="{T.width}: {points(style.width)}"
            aria-haspopup="dialog" onclick={(ev) => size(ev, 'width')}>
      <span class="style-btn__line" style:height="{Math.min(6, Math.max(1, style.width / 2))}px" aria-hidden="true"></span>
      <span class="style-btn__value">{NUMBER.format(style.width)}</span>
    </button>
  {/if}
  {#if style.fill != null}
    <button class="btn btn--icon tb-btn style-btn" type="button" title={T.fill} aria-label={T.fill} aria-haspopup="dialog" onclick={fill}>
      <span class="style-btn__fill" class:is-none={style.fill === NO_FILL} style:--swatch={style.fill} aria-hidden="true">
        <Icon name="paint-bucket" size={16} />
      </span>
    </button>
  {/if}
  {#if style.fontSize != null}
    <button class="btn btn--icon tb-btn style-btn style-btn--value" type="button" title={T.fontSize}
            aria-label="{T.fontSize}: {points(style.fontSize)}" aria-haspopup="dialog" onclick={(ev) => size(ev, 'fontSize')}>
      <Icon name="a-large-small" size={16} />
      <span class="style-btn__value">{NUMBER.format(style.fontSize)}</span>
    </button>
  {/if}
{/if}
