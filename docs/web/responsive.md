# Adaptación a cada pantalla

La misma interfaz sirve para móvil, tableta y escritorio, en la ventana de la app y en el navegador.
Las reglas están en [`styles/responsive.css`](../../app/ui/src/styles/responsive.css), que se carga la
última. Lo que CSS no puede resolver (abrir un panel, el zoom inicial) lee
[`lib/viewport.svelte.ts`](../../app/ui/src/lib/viewport.svelte.ts).

## Cortes

Son las clases de ventana de Material 3. Se usan estos y no otros: `viewport.svelte.ts` los repite.

| Clase | Ancho | Qué cambia |
|---|---|---|
| Compacto | < 600 | Móvil: paneles a pantalla completa, miniaturas en cajón, controles abajo |
| Medio | 600-839 | Una columna; el panel lateral flota sobre la página |
| Expandido | 840-1199 | Columnas laterales más estrechas |
| Grande | ≥ 1200 | Disposición completa |
| Extra grande | ≥ 1600 | El contenido deja de crecer (`.tool-page`, `.settings`, `.markdown`) |

Además del ancho:

| Condición | Efecto |
|---|---|
| `max-height: 500px` | Móvil en horizontal: sin barra de estado, con las barras opcionales ocultas |
| `pointer: coarse` | Dedo: objetivos de 40 px o más, y campos de 16 px para que Safari no acerque la página |
| `hover: none` | Lo que solo se veía al pasar el ratón queda siempre a la vista |
| `prefers-reduced-motion` | Sin transiciones |

Los cortes dependen del tamaño de la ventana, no del dispositivo: una ventana estrecha de escritorio se
comporta como una tableta. Por eso el tamaño mínimo de la ventana es 420 × 480 (`app/main.py`).

## Reglas

- **Nada queda fuera de alcance.** Lo que no cabe se agrupa, pasa a un menú o se desplaza. Un control
  que se oculta con `tb-wide` o `tb-zoom-group` tiene que seguir en `hiddenControls()` de
  `Viewer.svelte`.
- **Una tira que se desplaza lo dice** (`use:strip`, `lib/strip.ts`: pestañas, barras del visor,
  pestañas internas): el borde por el que sigue se difumina y la rueda del ratón la desplaza en
  horizontal. Con el dedo, se desliza.
- **Las filas de botones bajan de línea** antes que salirse o recortar el texto.
- **No se usa `:hover` como única forma de llegar a algo**: en el móvil no existe.
- **Las rejillas nuevas usan `auto-fill` con `minmax`**: se adaptan solas, sin cortes.

## Pestañas

Las de la cabecera (`shell/TabStrip.svelte`) no se aprietan: cada una muestra su nombre (hasta 240 px)
y, si no caben, la tira se desplaza. La activa siempre queda a la vista, también al cambiar el tamaño.

| | Ratón | Dedo | Teclado |
|---|---|---|---|
| Desplazar | rueda, flechas de los lados (solo si no caben) | deslizar | — |
| Cambiar de pestaña | clic | toque | ← → Inicio Fin sobre una pestaña; Ctrl+Tab, Ctrl+Re Pág / Av Pág |
| Reordenar | arrastrar (Escape la devuelve) | mantener pulsada y arrastrar | Ctrl+Shift+Re Pág / Av Pág |
| Menú (cerrar, mover…) | clic derecho | mantener pulsada sin mover | — |

Inicio va siempre la primera. Las vistas no cambian de sitio en la página al reordenar las pestañas
(`shell.views`, por orden de apertura): así no pierden su desplazamiento.

## La barra de anotaciones

Se compacta por niveles para caber (`use:fit`, `lib/fit.ts`, patrón «priority+»): mide el contenido de
verdad, así vale con ratón o con dedo y con el panel lateral abierto o cerrado.

| Nivel | Qué cambia |
|---|---|
| 0 | Todo a la vista |
| 1 | Los colores, en un botón con su menú; «Sellos» y «Firma», solo con su icono |
| 2 | Marcar texto, formas y trazos: un botón por grupo (la última herramienta usada; la flecha abre las demás) |
| 3 | También navegar e insertar (que suma los sellos y la firma) |

## El visor en un móvil

- La página se abre **ajustada al ancho**, y se reajusta al girar el móvil.
- Las herramientas de anotación empiezan ocultas: se abren con el lápiz de la barra.
- En una pantalla táctil la herramienta inicial es la **mano**. Arrastrar desplaza con cualquier
  herramienta, salvo las de texto y las de dibujo: arrastrar selecciona o dibuja, porque es lo que se
  ha pedido al elegirlas.
- Al ir a la página, el panel se aparta (`leavePanel`): tras elegir un sello, un resultado de búsqueda
  o un marcador. Si no, taparía lo que hay que ver o tocar.

## Cómo comprobarlo

Con el emulador de dispositivos del navegador, en `pnpm dev:web`: 320 × 568 (mínimo de WCAG, equivale a
una ventana de 1280 px al 400 %), 390 × 844, 844 × 390, 768 × 1024, 1024 × 700, 1440 × 900 y 2560 × 1440.

La simulación de gestos `Input.synthesizeScrollGesture` de Chrome no desplaza el lienzo: para probar
el dedo hay que enviar eventos de toque (`Input.dispatchTouchEvent`).

## Limitaciones conocidas

- **Reordenar arrastrando** las miniaturas del visor y las páginas en Unir no funciona con el dedo:
  usa arrastre HTML, que las pantallas táctiles no tienen. En el visor están «Mover página arriba» y
  «abajo» en el menú ⋮. Las pestañas sí (`tab-drag.ts`, con eventos de puntero).
- **Probado en emulación**, no en teléfonos físicos.
