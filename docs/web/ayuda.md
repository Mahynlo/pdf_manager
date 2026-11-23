# La Ayuda: cómo se escriben las guías

La pestaña **Ayuda** (`app/ui/src/tools/help/Help.svelte`) muestra las guías de
[`src/assets/ayuda/`](../../src/assets/ayuda/) y una de **atajos de teclado** que no es un archivo: sale
de la misma lista que Configuración (`t.settings.shortcuts`), así no se desincronizan.

El servicio `help` (`app/backend/services/help.py`) convierte cada guía a HTML sin HTML crudo
(`html=False`: seguro para insertarlo tal cual) y da su título, icono, resumen e índice. También tiene
el buscador (`help.search`: todas las palabras, sin tildes ni mayúsculas, por secciones).

## Una guía

```markdown
# 📄 Visor de PDF                                    ← título; el emoji es su icono en la lista
Leer un documento, moverte por él y organizar…       ← resumen (el primer párrafo), bajo el título

## Las partes del visor                              ← cada «##» es una entrada del índice
![El visor con sus partes numeradas](/ayuda_img/visor.png)
```

* **Orden:** el número del nombre del archivo (`01_INICIO.md`, `02_VISOR DE PDF.md`…), con dos cifras.
* **Teclas:** una combinación escrita como código se muestra como teclas: `` `Ctrl+S` `` →
  <kbd>Ctrl</kbd>+<kbd>S</kbd>. Vale para `Ctrl`, `Shift`, `Alt`, `Supr`, `Intro`, `Esc`, `Tab`,
  `Inicio`, `Fin`, `Re Pág`, `Av Pág`, `F1`…`F12`, flechas, letras y cifras sueltas. El resto de código se
  queda como código (`1,3-5`).
* **Recuadros:** una cita que empieza por `**Consejo:**`, `**Importante:**` (o `**Atención:**`) o
  `**Nota:**` sale como recuadro verde, ámbar o azul. Una cita sin eso, como cita normal.
* **Enlaces:**
    * `[texto](#seccion)`: una sección de la misma guía (el id es el título sin tildes, en minúsculas y con guiones).
    * `[texto](ayuda:visor)`: otra guía, la primera cuyo archivo contiene «visor». `ayuda:atajos` abre los atajos.
    * `[texto](https://…)`: se abre en el navegador.
* **Imágenes:** en `src/assets/ayuda_img/`, enlazadas como `/ayuda_img/x.png`. Se incrustan en el HTML
  (no se sirve nada fuera de esa carpeta) y se amplían al pulsarlas.

Cada guía explica la herramienta por pasos y con las palabras de sus botones. Las capturas llevan números,
y una tabla bajo la imagen dice qué es cada uno.

## Las capturas

Se generan solas desde la versión de navegador, con un PDF y unas imágenes de ejemplo (nada personal):
[`installer/ayuda/capturas.py`](../../installer/ayuda/capturas.py). Cuando cambie la interfaz:

```
cd app/ui && pnpm build:web && pnpm preview:web          # en otra terminal (puerto 5174)
uv run --with playwright python installer/ayuda/capturas.py
```

Cada captura es una lista de `(selector o Locator, número, dónde va el número)`. Si cambia un número,
cambia también la tabla de la guía que la usa.

## Pruebas

`tests/test_app_backend.py` (las de `help`): Markdown seguro, título/icono/resumen, índice, teclas,
recuadros, buscador, imágenes solo de la carpeta de recursos, y que todas las guías reales tengan título,
icono y resumen, que sus imágenes existan y que haya guía para cada enlace `ayuda:`.
