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

- **Nada queda fuera de alcance.** Lo que no cabe se desplaza (`.viewer-toolbar`, `.subtabs__bar`) o
  pasa a un menú. Un control que se oculta con `tb-wide` o `tb-zoom-group` tiene que seguir en
  `hiddenControls()` de `Viewer.svelte`.
- **Las filas de botones bajan de línea** antes que salirse o recortar el texto.
- **No se usa `:hover` como única forma de llegar a algo**: en el móvil no existe.
- **Las rejillas nuevas usan `auto-fill` con `minmax`**: se adaptan solas, sin cortes.

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

- **Reordenar arrastrando** (miniaturas del visor, páginas en Unir) no funciona con el dedo: usa arrastre
  HTML, que las pantallas táctiles no tienen. En el visor están «Mover página arriba» y «abajo» en el menú ⋮.
- **Probado en emulación**, no en teléfonos físicos.
