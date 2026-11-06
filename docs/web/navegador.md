# La app en un navegador

La misma app funciona en un navegador, sin instalar nada y sin servidor propio: es una página
estática. Los PDF no salen del equipo del usuario.

```powershell
cd app/ui
pnpm build:web     # compila a app/ui/dist-web/
pnpm preview:web   # la sirve en http://localhost:5174
pnpm dev:web       # o con recarga al guardar
```

## Cómo funciona

No hay una segunda implementación: corre el **mismo Python** (`app/backend` y `src/pdf_core`),
compilado a wasm con [Pyodide](https://pyodide.org), dentro de un Web Worker. Solo cambia lo que hay
detrás de [`api.ts`](../../app/ui/src/lib/api.ts).

```
ventana (Svelte, EmbedPDF)  ──llamadas──▶  worker: Pyodide
   lib/browser/client.ts    ◀──eventos───    lib/browser/worker.ts
        ▲                                    app/browser/main.py
        │ peticiones (diálogos, EmbedPDF)     app/backend, pdf_core
        └─────── memoria compartida ───────▶  (Python espera bloqueado)
```

| Pieza | Escritorio | Navegador |
|---|---|---|
| `Host` | `app/host.py` (`WebviewHost`) | `app/browser/host.py` (`BrowserHost`) |
| PDFium en Python | `pypdfium2` | `pypdfium2` (su wheel para Pyodide) |
| Motor de la ventana | EmbedPDF | EmbedPDF |
| Archivos | Rutas reales | Copias en el sistema de archivos virtual (`/files/…`) |
| Preferencias, leyendas, sellos y firmas | Perfil del usuario | IndexedDB (IDBFS en `/home/pyodide`) |
| Hilos | `threading` | `app/browser/background.py` |
| OCR | `onnxruntime` | `app/browser/onnx.py` sobre onnxruntime-web, con los mismos modelos |
| Datos grandes | `ByteServer` | URL `blob:` y `postMessage` |

### Python espera a la ventana

Los servicios son síncronos: `host.save_pdf()` devuelve la ruta elegida. En el navegador, Python
envía la petición y bloquea el worker con `Atomics.wait`; la ventana responde en memoria compartida
y lo despierta ([`protocol.ts`](../../app/ui/src/lib/browser/protocol.ts)). `postMessage` no sirve
para la respuesta, porque un worker bloqueado no recibe mensajes.

La memoria compartida exige que la página esté aislada: el servidor tiene que enviar estas cabeceras
(`pnpm preview:web` y `pnpm dev:web` ya lo hacen):

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

### Hilos

Pyodide no tiene hilos. Un hilo se guarda en una cola y se ejecuta justo después de responder a la
llamada que lo creó. Mientras dura, las demás llamadas esperan, salvo las de `INTERRUPTS`
(`extract.cancel`, `extract.answer_password`), que van por memoria compartida y se atienden en cada
evento que emite el trabajo. Si un trabajo nuevo tiene que poder interrumpirse, su método va en esa lista.

### Archivos

Los servicios siguen trabajando con rutas. La ventana da una ruta virtual a cada archivo que elige el
usuario y recuerda a qué archivo real corresponde. Tras cada llamada, `Files.changed` dice qué
escribieron los servicios, y [`files.ts`](../../app/ui/src/lib/browser/files.ts) lo entrega:

| | Chrome, Edge | Firefox, Safari |
|---|---|---|
| Abrir | File System Access | Selector de archivos, o soltar |
| Guardar | Sobre el archivo real | Se descarga |
| Guardar como | Diálogo del sistema | Se descarga con el nombre sugerido |
| Carpeta de salida | Diálogo del sistema | Cada archivo se descarga |

### Pantalla de carga

Mientras arranca Python se ve [`Splash.svelte`](../../app/ui/src/shell/Splash.svelte): el logo y una
barra con los pasos reales del arranque (evento `boot:progress`). Sale con el último tema usado, que
se copia en `localStorage` porque el guardado lo tiene Python. Si el arranque falla, el error se
muestra ahí mismo.

## Lo que cambia frente al escritorio

- **Recientes:** los archivos solo viven mientras la página está abierta, así que al recargar la lista queda vacía.
- **Abrir carpeta y mostrar el archivo:** no hacen nada.
- **«Abrir con» y barra de título:** no existen.
- **Asistente IA:** solo el modo básico, porque los clientes de los proveedores no están en Pyodide.
- **Durante una extracción** las demás herramientas esperan a que termine.
- **Memoria:** un worker de wasm tiene un límite de unos 2-4 GB, y cada PDF abierto está en Python y en EmbedPDF.

## Gotchas

- Un `null` de JavaScript llega a Python como `JsNull`, no como `None`, y es verdadero para `is not None`.
- IDBFS no guarda enlaces simbólicos: uno en `/home/pyodide` rompe el arranque siguiente.
- onnxruntime-web crea sus hilos cargando su propio script. Si Vite lo empaqueta, cada hilo arranca
  `onnx-worker` y el OCR se cuelga, **solo en producción**. Por eso `onnx/` va copiado aparte
  (`wasmPaths`). Vite sigue emitiendo una copia de su `.wasm` en `assets/`, que nadie pide.
- `app/backend` no puede importar `js` ni `pyodide`: lo propio del navegador va en `app/browser`.

## Compilación

[`installer/browser/prepare.py`](../../installer/browser/prepare.py) deja en `app/ui/public-web/`
(fuera de git) lo que carga la página. Baja los wheels con su suma comprobada, usa la versión de
`pypdfium2` de `uv.lock` y empaqueta el backend en `backend.zip`. Después de cambiar Python hay que
volver a ejecutarlo: `pnpm build:web` y `pnpm dev:web` ya lo hacen.

Pyodide, numpy y los demás se sirven desde la propia web, sin CDN en tiempo de uso.

La primera visita baja unos 16 MB comprimidos (después salen de la caché del navegador), y el OCR, otros 34 MB la primera vez que se usa.

## Pendiente

- **Publicarla.** GitHub Pages no deja poner las cabeceras COOP y COEP: haría falta un service worker
  que las añada, o usar Cloudflare Pages o Netlify, que sí las admiten.
- **Probar en Firefox y Safari**, que no se han probado, e imprimir en un navegador real.
- **Funcionar sin conexión** (PWA) y recordar los archivos recientes en Chrome y Edge.
