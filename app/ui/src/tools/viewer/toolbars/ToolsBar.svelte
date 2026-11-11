<!--
  Barra de herramientas del lienzo (AnnotSubBar en Qt): mano, selección de texto,
  puntero, anotaciones de texto, formas, trazos, texto e imagen, colores, sellos y firma.

  Se compacta para caber (lib/fit.ts, `data-level` en styles/viewer.css):
    0  todo a la vista;
    1  los colores en un botón y «Sellos» y «Firma» solo con su icono;
    2  marcar texto, formas y trazos: un botón por grupo (la última herramienta usada y, en la
       flecha, las demás);
    3  también navegar e insertar (que suma los sellos y la firma).
  Si ni así cabe, se desplaza (lib/strip.ts).
-->
<script lang="ts">
  import Icon from '$lib/Icon.svelte';
  import { fit } from '$lib/fit.ts';
  import { openMenu, type MenuItem } from '$lib/menu.svelte.ts';
  import { strip } from '$lib/strip.ts';
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
  const LEVELS = 3;

  interface ToolButton {
    key: string;
    icon: string;
    title: string;
  }

  interface ToolGroup {
    id: string;
    label: string;
    collapse: 2 | 3; // nivel desde el que va en un solo botón
    tools: ToolButton[];
  }

  const GROUPS: ToolGroup[] = [
    {
      id: 'navigate', label: T.groups.navigate, collapse: 3, tools: [
        { key: TOOLS.HAND, icon: 'hand', title: T.hand },
        { key: TOOLS.SELECT, icon: 'text-cursor', title: T.select },
        { key: TOOLS.POINTER, icon: 'pointer', title: T.pointer },
      ],
    },
    {
      id: 'markup', label: T.groups.markup, collapse: 2, tools: [
        { key: TOOLS.HIGHLIGHT, icon: 'highlighter', title: T.highlight },
        { key: TOOLS.UNDERLINE, icon: 'underline', title: T.underline },
        { key: TOOLS.STRIKEOUT, icon: 'strikethrough', title: T.strikeout },
        { key: TOOLS.SQUIGGLY, icon: 'squiggly', title: T.squiggly },
        { key: TOOLS.INSERT_TEXT, icon: 'text-insert', title: T.insertText },
        { key: TOOLS.REPLACE_TEXT, icon: 'text-replace', title: T.replaceText },
      ],
    },
    {
      id: 'shapes', label: T.groups.shapes, collapse: 2, tools: [
        { key: TOOLS.RECT, icon: 'square', title: T.rect },
        { key: TOOLS.ELLIPSE, icon: 'circle', title: T.ellipse },
        { key: TOOLS.LINE, icon: 'line', title: T.line },
        { key: TOOLS.ARROW, icon: 'arrow-up-right', title: T.arrow },
        { key: TOOLS.POLYLINE, icon: 'polyline', title: T.polyline },
        { key: TOOLS.POLYGON, icon: 'pentagon', title: T.polygon },
      ],
    },
    {
      id: 'draw', label: T.groups.draw, collapse: 2, tools: [
        { key: TOOLS.PEN, icon: 'squiggle', title: T.pen },
        { key: TOOLS.MARKER, icon: 'brush', title: T.marker },
        { key: TOOLS.DRAW, icon: 'pencil', title: T.draw },
      ],
    },
    {
      id: 'insert', label: T.groups.insert, collapse: 3, tools: [
        { key: TOOLS.TEXT, icon: 'type', title: T.text },
        { key: TOOLS.IMAGE, icon: 'image', title: T.image },
      ],
    },
  ];

  // El botón de texto también vale para la llamada y la nota (clic derecho, como en Qt).
  const TEXT_VARIANTS: ToolButton[] = [
    { key: TOOLS.TEXT, icon: 'type', title: T.textMenu.text },
    { key: TOOLS.CALLOUT, icon: 'message-square', title: T.textMenu.callout },
    { key: TOOLS.NOTE, icon: 'file-text', title: T.textMenu.note },
  ];
  const TEXT_KEYS = new Set(TEXT_VARIANTS.map(({ key }) => key));
  const isActive = (key: string) => tool === key || (key === TOOLS.TEXT && TEXT_KEYS.has(tool));

  /** El botón de cada herramienta, también las variantes del texto. */
  const BUTTONS = new Map([...GROUPS.flatMap((group) => group.tools), ...TEXT_VARIANTS].map((b) => [b.key, b]));
  const groupOf = (key: string) => GROUPS.find((group) => group.tools.some((b) => b.key === key || (b.key === TOOLS.TEXT && TEXT_KEYS.has(key))));

  // La última herramienta usada de cada grupo: la que muestra su botón cuando se compacta.
  let remembered = $state<Record<string, string>>({});
  $effect(() => {
    const group = groupOf(tool);
    if (group) remembered[group.id] = tool;
  });
  const shownTool = (group: ToolGroup) => BUTTONS.get(remembered[group.id] ?? group.tools[0].key)!;
  const groupActive = (group: ToolGroup) => group.tools.some((b) => isActive(b.key));

  function textMenu(ev: MouseEvent & { currentTarget: HTMLElement }, key: string) {
    if (key !== TOOLS.TEXT) return;
    ev.preventDefault();
    openMenu(ev.currentTarget, TEXT_VARIANTS.map((b) => toolItem(b, b.title)));
  }

  function toolItem(button: ToolButton, label = button.title): MenuItem {
    return { label, icon: button.icon, checked: tool === button.key, onSelect: () => setTool(button.key) };
  }

  /** Las herramientas de un grupo compactado; insertar suma las variantes del texto, los sellos y la firma. */
  function groupMenu(ev: MouseEvent & { currentTarget: HTMLElement }, group: ToolGroup) {
    const items: MenuItem[] = group.id === 'insert'
      ? [
        ...TEXT_VARIANTS.map((b) => toolItem(b)),
        toolItem(BUTTONS.get(TOOLS.IMAGE)!),
        'separator',
        { label: T.stampsTip, icon: 'stamp', onSelect: stamps },
        { label: T.signaturesTip, icon: 'signature', onSelect: signatures },
      ]
      : group.tools.map((b) => toolItem(b));
    openMenu(ev.currentTarget.parentElement!, items);
  }

  function paletteMenu(ev: MouseEvent & { currentTarget: HTMLElement }) {
    openMenu(ev.currentTarget, PALETTE.map(([color, name]) => ({ label: T.color(name), color, onSelect: () => setColor(color) })));
  }
</script>

{#snippet toolButton({ key, icon, title }: ToolButton)}
  <button class="btn btn--icon tb-btn" class:is-checked={isActive(key)} type="button" {title} aria-label={title}
          aria-pressed={isActive(key)} onclick={() => setTool(key)} oncontextmenu={(ev) => textMenu(ev, key)}>
    <Icon name={icon} size={18} />
  </button>
{/snippet}

<div class="viewer-toolbar viewer-toolbar--tools" role="toolbar" aria-label={T.label} hidden={!visible}
     use:fit={{ levels: LEVELS }} use:strip>
  {#each GROUPS as group (group.id)}
    <div class="tb-group" role="group" aria-label={group.label} data-collapse={group.collapse}>
      <div class="tb-group__all">
        {#each group.tools as button (button.key)}{@render toolButton(button)}{/each}
      </div>
      <div class="tb-split" class:is-checked={groupActive(group)}>
        {@render toolButton(shownTool(group))}
        <button class="tb-split__more" type="button" title={T.more(group.label)} aria-label={T.more(group.label)}
                aria-haspopup="menu" onclick={(ev) => groupMenu(ev, group)}>
          <Icon name="chevron-down" size={12} />
        </button>
      </div>
    </div>
    <span class="tb-sep" aria-hidden="true"></span>
  {/each}
  <div class="tb-swatches" role="group" aria-label={T.colors}>
    {#each PALETTE as [color, name] (color)}
      <button class="tb-swatch" type="button" title={T.color(name)} aria-label={T.color(name)} style:--swatch={color}
              onclick={() => setColor(color)}></button>
    {/each}
  </div>
  <button class="btn btn--icon tb-btn tb-palette" type="button" title={T.colors} aria-label={T.colors}
          aria-haspopup="menu" onclick={paletteMenu}>
    <Icon name="palette" size={18} />
  </button>
  <div class="tb-insert-extra">
    <button class="btn btn--ghost tb-btn tb-text-btn" class:is-checked={tool === TOOLS.PLACE} type="button"
            title={T.stampsTip} aria-label={T.stampsTip} onclick={stamps}>
      <Icon name="stamp" size={18} /><span class="tb-label">{T.stamps}</span>
    </button>
    <button class="btn btn--ghost tb-btn tb-text-btn" type="button" title={T.signaturesTip} aria-label={T.signaturesTip}
            onclick={signatures}>
      <Icon name="signature" size={18} /><span class="tb-label">{T.signatures}</span>
    </button>
  </div>
</div>
