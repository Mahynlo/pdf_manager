<!--
  Barra de herramientas del lienzo (AnnotSubBar en Qt): mano, selección de texto,
  puntero, anotaciones de texto, formas, trazos, texto e imagen, colores y sellos.
-->
<script>
  import Icon from '$lib/Icon.svelte';
  import { openMenu } from '$lib/menu.svelte.js';
  import { TOOLS } from './canvas.js';
  import { PALETTE } from './palette.js';

  /** `tool`: herramienta activa; `setTool(t)`, `setColor(hex)`, `stamps(botón)`: menú «Sellos». */
  let { tool, setTool, setColor, stamps } = $props();

  const GROUPS = [
    [
      { key: TOOLS.HAND, icon: 'hand', title: 'Mano: Desplazar página / Panning' },
      { key: TOOLS.SELECT, icon: 'text-cursor', title: 'Seleccionar Texto: Copiar, buscar y resaltar texto' },
      { key: TOOLS.POINTER, icon: 'pointer', title: 'Puntero de Objetos: Seleccionar, mover y transformar anotaciones' },
    ],
    [
      { key: TOOLS.HIGHLIGHT, icon: 'highlighter', title: 'Resaltar texto' },
      { key: TOOLS.UNDERLINE, icon: 'underline', title: 'Subrayar texto' },
      { key: TOOLS.STRIKEOUT, icon: 'strikethrough', title: 'Tachar texto' },
      { key: TOOLS.SQUIGGLY, icon: 'squiggly', title: 'Subrayado ondulado' },
      { key: TOOLS.INSERT_TEXT, icon: 'text-insert', title: 'Indicar texto omitido: selecciona dónde va y escribe lo que falta' },
      { key: TOOLS.REPLACE_TEXT, icon: 'text-replace', title: 'Reemplazar texto: selecciona lo que sobra y escribe el texto nuevo' },
    ],
    [
      { key: TOOLS.RECT, icon: 'square', title: 'Forma: Rectángulo' },
      { key: TOOLS.ELLIPSE, icon: 'circle', title: 'Forma: Círculo / Elipse' },
      { key: TOOLS.LINE, icon: 'line', title: 'Línea' },
      { key: TOOLS.ARROW, icon: 'arrow-up-right', title: 'Flecha' },
      { key: TOOLS.POLYLINE, icon: 'polyline', title: 'Polilínea: clic en cada vértice, doble clic para terminar' },
      { key: TOOLS.POLYGON, icon: 'pentagon', title: 'Polígono: clic en cada vértice, doble clic para cerrar' },
    ],
    [
      { key: TOOLS.PEN, icon: 'squiggle', title: 'Trazos libres / Pluma' },
      { key: TOOLS.MARKER, icon: 'brush', title: 'Marcador: trazo libre translúcido' },
      { key: TOOLS.DRAW, icon: 'pencil', title: 'Dibujo fino' },
    ],
    [
      { key: TOOLS.TEXT, icon: 'type', title: 'Insertar texto en página (T) - Clic derecho para opciones' },
      { key: TOOLS.IMAGE, icon: 'image', title: 'Imagen: elige un archivo y haz clic donde colocarla' },
    ],
  ];

  // El botón de texto también vale para la llamada y la nota (clic derecho, como en Qt).
  const TEXT_VARIANTS = new Set([TOOLS.TEXT, TOOLS.CALLOUT, TOOLS.NOTE]);
  const isActive = (key) => tool === key || (key === TOOLS.TEXT && TEXT_VARIANTS.has(tool));

  function textMenu(ev, key) {
    if (key !== TOOLS.TEXT) return;
    ev.preventDefault();
    openMenu(ev.currentTarget, [
      { label: 'Texto libre en página (T)', icon: 'type', onSelect: () => setTool(TOOLS.TEXT) },
      { label: 'Texto con flecha (llamada)', icon: 'message-square', onSelect: () => setTool(TOOLS.CALLOUT) },
      { label: 'Nota adhesiva (comentario)', icon: 'file-text', onSelect: () => setTool(TOOLS.NOTE) },
    ]);
  }
</script>

<div class="viewer-toolbar viewer-toolbar--tools" role="toolbar">
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
    <button class="tb-swatch" type="button" title="Color {name}" aria-label="Color {name}" style:--swatch={color}
            onclick={() => setColor(color)}></button>
  {/each}
  <button class="btn btn--ghost tb-btn tb-text-btn" type="button" title="Sellos y leyendas de texto"
          onclick={(ev) => stamps(ev.currentTarget)}>
    <Icon name="stamp" size={18} />Sellos<Icon name="chevron-down" size={14} />
  </button>
</div>
