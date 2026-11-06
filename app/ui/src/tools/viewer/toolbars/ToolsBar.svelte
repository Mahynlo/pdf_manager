<!--
  Barra de herramientas del lienzo (AnnotSubBar en Qt): mano, selección de texto,
  puntero, anotaciones de texto, formas, trazos, texto e imagen, colores, sellos y firma.
-->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.ts';
  import { TOOLS } from '../canvas/canvas.ts';
  import { PALETTE } from '../annotations/palette.ts';
  import { t } from '$texts';

  /**
   * `tool`: herramienta activa; `setTool(t)`, `setColor(hex)`; `stamps()`, `signatures()`: abrir
   * el panel de sellos o el de firmas; `visible`: en el móvil, la barra se abre al pedirla.
   */
  let { tool, setTool, setColor, stamps, signatures, visible }: {
    visible: boolean;
    tool: string;
    setTool: (tool: string) => void;
    setColor: (color: string) => void;
    stamps: () => void;
    signatures: () => void;
  } = $props();

  const T = t.viewer.tools;

  const GROUPS = [
    [
      { key: TOOLS.HAND, icon: 'hand', title: T.hand },
      { key: TOOLS.SELECT, icon: 'text-cursor', title: T.select },
      { key: TOOLS.POINTER, icon: 'pointer', title: T.pointer },
    ],
    [
      { key: TOOLS.HIGHLIGHT, icon: 'highlighter', title: T.highlight },
      { key: TOOLS.UNDERLINE, icon: 'underline', title: T.underline },
      { key: TOOLS.STRIKEOUT, icon: 'strikethrough', title: T.strikeout },
      { key: TOOLS.SQUIGGLY, icon: 'squiggly', title: T.squiggly },
      { key: TOOLS.INSERT_TEXT, icon: 'text-insert', title: T.insertText },
      { key: TOOLS.REPLACE_TEXT, icon: 'text-replace', title: T.replaceText },
    ],
    [
      { key: TOOLS.RECT, icon: 'square', title: T.rect },
      { key: TOOLS.ELLIPSE, icon: 'circle', title: T.ellipse },
      { key: TOOLS.LINE, icon: 'line', title: T.line },
      { key: TOOLS.ARROW, icon: 'arrow-up-right', title: T.arrow },
      { key: TOOLS.POLYLINE, icon: 'polyline', title: T.polyline },
      { key: TOOLS.POLYGON, icon: 'pentagon', title: T.polygon },
    ],
    [
      { key: TOOLS.PEN, icon: 'squiggle', title: T.pen },
      { key: TOOLS.MARKER, icon: 'brush', title: T.marker },
      { key: TOOLS.DRAW, icon: 'pencil', title: T.draw },
    ],
    [
      { key: TOOLS.TEXT, icon: 'type', title: T.text },
      { key: TOOLS.IMAGE, icon: 'image', title: T.image },
    ],
  ];

  // El botón de texto también vale para la llamada y la nota (clic derecho, como en Qt).
  const TEXT_VARIANTS = new Set<string>([TOOLS.TEXT, TOOLS.CALLOUT, TOOLS.NOTE]);
  const isActive = (key: string) => tool === key || (key === TOOLS.TEXT && TEXT_VARIANTS.has(tool));

  function textMenu(ev: MouseEvent & { currentTarget: HTMLElement }, key: string) {
    if (key !== TOOLS.TEXT) return;
    ev.preventDefault();
    openMenu(ev.currentTarget, [
      { label: T.textMenu.text, icon: 'type', onSelect: () => setTool(TOOLS.TEXT) },
      { label: T.textMenu.callout, icon: 'message-square', onSelect: () => setTool(TOOLS.CALLOUT) },
      { label: T.textMenu.note, icon: 'file-text', onSelect: () => setTool(TOOLS.NOTE) },
    ]);
  }
</script>

<div class="viewer-toolbar viewer-toolbar--tools" role="toolbar" hidden={!visible}>
  {#each GROUPS as group, g (g)}
    {#each group as { key, icon, title } (key)}
      <button class="btn btn--icon tb-btn" class:is-checked={isActive(key)} type="button" {title} aria-label={title}
              aria-pressed={isActive(key)} onclick={() => setTool(key)} oncontextmenu={(ev) => textMenu(ev, key)}>
        <Icon name={icon} size={18} />
      </button>
    {/each}
    <span class="tb-sep" aria-hidden="true"></span>
  {/each}
  {#each PALETTE as [color, name] (color)}
    <button class="tb-swatch" type="button" title={T.color(name)} aria-label={T.color(name)} style:--swatch={color}
            onclick={() => setColor(color)}></button>
  {/each}
  <button class="btn btn--ghost tb-btn tb-text-btn" class:is-checked={tool === TOOLS.PLACE} type="button"
          title={T.stampsTip} onclick={stamps}>
    <Icon name="stamp" size={18} />{T.stamps}
  </button>
  <button class="btn btn--ghost tb-btn tb-text-btn" type="button" title={T.signaturesTip} onclick={signatures}>
    <Icon name="signature" size={18} />{T.signatures}
  </button>
</div>
