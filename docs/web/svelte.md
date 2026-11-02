# Interfaz en Svelte (`app/ui`)

La interfaz de la app está escrita en **Svelte 5** y se compila con **Vite**. El backend sigue en
**Python**: los componentes llaman a sus servicios con `call`/`on`, a través de pywebview.

Sustituyó por completo a la interfaz anterior en JS sin framework (`app/frontend`, ya eliminada;
sigue en el historial de git).

## Estructura

```
app/ui/
  package.json          versiones fijas: svelte, vite, @sveltejs/vite-plugin-svelte, typescript,
                        svelte-check; `pnpm check` comprueba los tipos
  tsconfig.json         TypeScript (ver «TypeScript»); alias $lib y $texts
  vite.config.ts        compila a dist/; alias $lib → src/lib, $texts → src/texts (Svelte usa
                        su configuración predeterminada: no hay svelte.config.js)
  index.html            página base (Vite inserta los módulos)
  src/
    main.ts             arranque: estilos, tema guardado, monta App y avisa a Python (app.ready)
    styles/             estilos globales: tokens.css (colores del tema), base, componentes y uno
                        por área (shell, merge, security, extract, settings, help, viewer)
    assets/icons.json   trazos de los iconos (también los usa la versión Qt)
    App.svelte          ventana: cabecera con pestañas, vistas, barra de estado, avisos y menú
    texts/              textos de la interfaz: es/ (catálogo: un archivo por herramienta, shell.ts
                        para la ventana y common.ts para los diálogos de lib/) e index.ts (t, tip())
    lib/                piezas comunes
      api.ts            puente con Python: call('servicio.metodo', ...), on('evento', fn)
      types.ts          tipos de las respuestas de Python que usan varias partes (DocumentInfo…)
      ui.ts             toast(), setStatus() y diálogos: askChoice, confirmDialog, askText,
                        askPassword, progressDialog, openModal
      menu.svelte.ts    openMenu(botón, opciones) / openMenuAt(x, y, opciones)
      theme.svelte.ts   tema claro/oscuro compartido (theme.dark, theme.toggle())
      thumbs.ts         miniaturas bajo demanda (ThumbLoader y la acción use:thumb)
      Icon.svelte       iconos del juego común (assets/icons.json)
      dom.ts, icons.ts  h() e ic(): solo para el código imperativo del lienzo
      components/       Dialog y los diálogos de ui.ts; controles: PasswordField, Checkbox,
                        RadioGroup, Fieldset, Banner, SubTabs, SectionCard, ToolHeader, Menu
    shell/              shell.svelte.ts (estado de las pestañas), tools.ts (registro de
                        herramientas), Home y RecentFiles (Inicio), dropzone.ts
    tools/
      settings/  help/  security/  merge/  extract/
      viewer/           Viewer.svelte y sus piezas (ver abajo)
  dist/                 compilación (se genera, no se versiona)
```

### El visor

`Viewer.svelte` compone el visor y conecta sus piezas:
- **Componentes:**
  - barras (`toolbars/`): `Toolbar`, `ToolsBar`;
  - miniaturas: `panels/Thumbnails`;
  - panel lateral: `panels/TocTree`, `panels/SearchPanel`, `ocr/OcrPanel`, `redact/RedactPanel`, `panels/AiPanel`;
  - diálogos: imprimir, propiedades, leyendas, perfiles de censura y OCR por lotes.
- **Lienzo, en código imperativo:** `canvas/canvas.ts`, `canvas/selection.ts`, `annotations/annotations.ts` y
  `annotations/editing.ts`. Qué hay en cada carpeta: `app/ui/src/tools/viewer/README.md`.
  - Las páginas, el scroll y el zoom son de EmbedPDF (`embed.ts`, `EmbedRoot.svelte`, `PdfPages.svelte`, `PdfPage.svelte`), y también la selección de texto, la búsqueda y las anotaciones;
    `canvas.ts` da al resto la misma API que antes. El visor se está pasando a EmbedPDF paso a paso:
    ver [embedpdf.md](embedpdf.md).
  - Pintan miles de elementos (páginas, letras, anotaciones) y los actualizan a mano, por rendimiento.
  - El componente los crea y coloca su elemento en la página.
  - Escucha sus avisos (página, zoom, anotaciones) para actualizar el resto.

## Uso

Todo se lanza desde la raíz del proyecto, con un solo comando. Hacen falta Node.js y pnpm (solo para
desarrollar; el ejecutable ya lleva la interfaz compilada).

| Para | Comando |
|---|---|
| Abrir la app | `uv run python -m app.main` |
| Desarrollar con recarga al guardar | `uv run python -m app.main --dev` |

- **Arranque normal:** `app/ui_dev.py` compila la interfaz (`pnpm build`) si falta la compilación o
  si algún archivo de `app/ui` cambió desde la última.
- **`--dev`:** arranca `pnpm dev` (o usa el que ya esté en marcha), espera a que responda, abre la
  ventana contra él y lo detiene al cerrar la app. Al guardar un `.svelte`, la ventana se actualiza sola.
- **Dependencias:** si falta `node_modules`, ejecuta antes `pnpm install`.
- **`--dev-server URL`:** abre un servidor de Vite que hayas arrancado tú.
- **En un navegador:** la URL de `pnpm dev` no sirve sola, porque la interfaz necesita el backend
  de Python, que solo existe dentro de la ventana. La página lo explica en vez de quedarse en blanco.

El instalador (`installer/web/build.ps1`) comprueba los tipos (`pnpm check`) y compila la
interfaz antes de empaquetar: con errores de tipos no genera el ejecutable.

Para comprobar los tipos a mano: `pnpm check` en `app/ui`.

## TypeScript

Toda la interfaz (`src/`) está en TypeScript, en modo `strict`: no queda ningún `.js`. Vite compila
los `.ts` y los componentes con `<script lang="ts">` sin más configuración, y `svelte-check`
(`pnpm check`) comprueba los tipos. También la configuración de Vite (`vite.config.ts`) está en
TypeScript; no hay `svelte.config.js` porque Svelte usa su configuración predeterminada.

- **Respuestas de Python:** las que usan varias partes, en `lib/types.ts` (`DocumentInfo`…); las de
  una herramienta, en su carpeta (`tools/merge/types.ts`, `tools/viewer/ocr/types.ts`, …).
- **Partes internas de EmbedPDF:** el visor usa cuatro métodos privados de EmbedPDF 2.15.1
  (`register` del historial, `searchAllPages` con `force`, `endSelection` y la estrategia de
  scroll paginada). Cada uno tiene su interfaz con un comentario que lo explica (`HistoryInternals`,
  `ForcedSearch`, `SelectionInternals`, `ScrollInternals`): al actualizar EmbedPDF hay que revisarlos.
- **Importaciones con la extensión real:** `'$lib/api.ts'`, `'./menu.svelte.ts'` (`allowImportingTsExtensions`).
- **Respuestas de Python con tipo:** `call<Tipo>('servicio.metodo', …)` y `on<Tipo>('evento', fn)`; sin tipo devuelven `any`.
- **Archivos nuevos:** en TypeScript (`.ts` y `lang="ts"`).
- **Tipos de las props:** `let { view, actions }: { view: ToolbarView; actions: ToolbarActions } = $props();`.
- **Sin parámetros opcionales con `?` en los componentes:** en un `<script lang="ts">`, Svelte 5.51
  quita el tipo de `function log(text: string, tone?: LogTone)` pero deja el `?`, y la compilación
  falla (`pnpm check` no lo detecta). Se usa un valor por defecto: `tone: LogTone = null`. En los
  `.ts` y dentro de un tipo (`{ checked?: boolean }`) no hay problema.
- **Comprobar siempre con `pnpm check` y `pnpm build`:** algunos fallos solo salen al compilar.

## Textos de la interfaz

Los nombres de botones, descripciones emergentes, menús y avisos van en el catálogo
`src/texts/es/`, un archivo por herramienta (`viewer.ts`, `merge.ts`, …) reunidos en `es/index.ts`,
y dentro ordenados por parte de la interfaz (`t.viewer.toolbar.undo`). Para cambiar un texto se edita
ahí, sin buscarlo por el código.

```svelte
<script lang="ts">
  import { t, tip } from '$texts';
  const T = t.viewer.toolbar;
</script>

<button title={tip(T.undo)}>…</button>   <!-- «Deshacer (Ctrl+Z)» -->
```

- **Atajos:** los botones con atajo llevan `{ label, shortcut }`; `tip()` los une en
  «Etiqueta (atajo)».
- **Con datos:** un texto con datos es una función (`` color: (name) => `Color ${name}` ``).
- **Comprobado:** en los componentes con `lang="ts"`, una clave que no existe es un error de
  `pnpm check` («Did you mean 'dock'?»).
- **Otro idioma:** sería otro catálogo con las mismas claves (`const en: Texts = { … }`).
- **Todo en el catálogo:** cada herramienta en su archivo (el visor, Ajustes con la lista de
  atajos, Ayuda con «Información general», Seguridad, Extraer y Combinar); la ventana principal en
  `shell.ts` (cabecera, pestañas, Inicio, recientes, nombres y tarjetas de las herramientas, aviso
  al salir y mensajes de arranque), y los botones y diálogos de `lib/` en `common.ts` («Cancelar»,
  «Sí/No», contraseña).
- **Fuera del catálogo:** los manuales de Ayuda (Markdown en `docs/ayuda/`) y los mensajes de error
  del backend Python.

## Escribir componentes

```svelte
<script lang="ts">
  import { call, on } from '$lib/api.ts';
  import { toast } from '$lib/ui.ts';

  let { tool } = $props();          // entrada del registro (shell/tools.ts)
  let merge = $state.raw(null);
  call('merge.state').then((s) => (merge = s)).catch((err) => toast(err.message, 'danger'));

  $effect(() => on('merge:progress', ({ done, total }) => { /* ... */ })); // se desuscribe al desmontar

  export function canClose() { return true; } // opcional: el shell la llama antes de cerrar la pestaña
</script>
```

- **Servicios y eventos:** los de `app/backend/services` (ver [arquitectura.md](arquitectura.md)).
  - Los errores llegan como `ApiError`, con `code` y `message`.
- **Funciones de pestaña:** un componente de herramienta puede exportar `canClose()`, `onKey(ev)` y `onShow()`.
  - El shell las llama a través de su instancia.
  - Para liberar recursos al cerrar la pestaña se usa `onDestroy`.
- **Diálogos:** son componentes que reciben `done(valor)`.
  - Se abren con `openModal(Componente, props)`, que resuelve ese valor.
  - Se basan en `<Dialog>`.
- **Nombres:** no llames `state` a una variable ni a una prop, porque choca con la runa `$state`.
  - Usa nombres como `merge`, `job` o `progress`.
- **Iconos:** se escriben como `<Icon name="…">`.
  - En los fragmentos (`{#snippet}`), el icono va como primer argumento.
  - En las tablas de datos, va en una clave `icon:`.
  - Así los tests encuentran todos los iconos.
- **Estilos:**
  - Los globales están en `src/styles/` (importados en `src/main.ts`).
  - Los nuevos van en el bloque `<style>` del componente, que Svelte aísla.
  - Los colores y medidas salen siempre de las variables de `tokens.css`, para que el tema funcione.

## Tests

Los tests de `tests/test_app_backend.py` revisan `app/ui/src`:
- cada icono usado existe en `icons.json`;
- cada `call('servicio.metodo')` existe en el backend.

## Estado

Todas las pantallas están migradas:
- shell e Inicio;
- Ajustes y Ayuda;
- Seguridad, Combinar y Extraer;
- el visor completo: lienzo, anotaciones, sellos, búsqueda, OCR, censura, IA, impresión y operaciones de página.

Se probó en la app real comparándola con la interfaz anterior, antes de retirarla. Las dos se comportaron igual en:
- navegación, zoom, índice y búsqueda;
- envío de un término a censura, OCR de página y estado de la IA;
- sellos y deshacer/rehacer;
- insertar y eliminar páginas, propiedades e imprimir;
- aviso de cambios sin guardar al cerrar;
- todas las herramientas, el tema, la Ayuda y los atajos de pestañas.

No se pudieron automatizar los flujos que abren diálogos nativos de Windows (elegir archivos o carpetas). Hay que probarlos a mano:
- cargar PDFs en Combinar y combinarlos;
- elegir objetivos y extraer;
- proteger y desbloquear;
- guardar como.
