# Seguridad

Qué protege la app, de qué y dónde está cada medida, en el escritorio (pywebview + WebView2) y en el
navegador (Pyodide). Revisado el 2026-11-11.

## Modelo de amenazas

Los PDF y todo lo que se procesa se quedan en el equipo del usuario: no hay servidor propio. Lo que
llega de fuera, y por tanto no es de fiar:

| Entrada | Riesgo |
|---|---|
| **Un PDF** abierto o soltado | Texto, enlaces o anotaciones que intenten colar HTML o abrir programas; archivos mal formados contra el motor PDF |
| **Una respuesta de la IA** | Puede repetir texto del PDF preparado para ello («prompt injection») con HTML o enlaces |
| **Otra web abierta en el navegador** | Intentar llegar al servidor local de datos (escritorio) |
| **Otro programa u otro usuario del equipo** | Hablar con la tubería de la instancia única; leer la clave de la IA |
| **Las dependencias** | Una versión con una vulnerabilidad conocida |

En el escritorio el riesgo grave es que algo ejecute código en la ventana: ahí está el puente con
Python (`window.pywebview.api`), que lee y escribe archivos. Por eso se cierran en capas: no se pinta
HTML de fuera, la política de contenidos no ejecutaría el que se colara y la ventana nunca navega fuera.

## Medidas

### La interfaz

- **Política de contenidos (CSP)** en `index.html`, al compilar ([`app/ui/csp.ts`](../../app/ui/csp.ts)):
  solo scripts de la propia app (sin scripts en línea ni `eval`; sí wasm), nada de `<object>`, `<base>`
  ni formularios, iframes solo de `blob:` (imprimir) y conexiones solo a la propia app y, en el
  escritorio, a `127.0.0.1` (el servidor de datos). Los estilos en línea se permiten: los usan Svelte y
  EmbedPDF. Va en una etiqueta `<meta>` para que valga también donde no se pueden poner cabeceras
  (GitHub Pages). En desarrollo (`pnpm dev`) no se aplica.
- **Sin HTML de fuera.** El Markdown del asistente IA y de la Ayuda se convierte con `markdown-it` sin
  HTML crudo (`html: False`); en el de la IA, además, sin enlaces ni imágenes
  (`app/backend/services/ai.py`). Son los únicos `{@html}`, junto con los iconos propios.
- **Los enlaces de los PDF no se siguen**: EmbedPDF los tiene bloqueados (`locked`, `canvas/embed.ts`).
- **La ventana nunca sale de la app** ([`shell/navigation.ts`](../../app/ui/src/shell/navigation.ts)):
  un clic (también central o con Ctrl) en un enlace lo abre en el navegador del sistema, y soltar un
  enlace arrastrado desde otra web no lleva la ventana a esa página.
- **Enlaces externos**: solo `http`/`https` con servidor y `mailto`, sin caracteres de control
  (`is_external_url`, `app/backend/host.py`); lo usan los dos anfitriones. Nunca `file:`,
  `javascript:` ni rutas o programas locales. En el navegador se abren con `noopener,noreferrer`.
- **Contraseñas de PDF**: los campos usan `autocomplete="new-password"` (el navegador no las guarda) y
  no se registran en el log.

### El puente con Python (escritorio)

- El frontend solo llama a métodos marcados con `@exposed` (`app/backend/rpc.py`); cualquier otro
  nombre se rechaza. Por ejemplo, `documents.open` no está expuesto.
- Las herramientas de desarrollo de WebView2 solo se abren con `--debug`.

### El servidor local de datos (escritorio)

[`app/byte_server.py`](../../app/byte_server.py) pasa los datos grandes entre Python y la ventana:

- Solo escucha en `127.0.0.1`; cada dato tiene un código aleatorio de 256 bits, se sirve una vez y
  caduca a los 2 minutos.
- Solo atiende peticiones dirigidas a `127.0.0.1:<puerto>` (cabecera `Host`): una web cuyo dominio
  apunte a 127.0.0.1 («DNS rebinding») recibe 403.
- Una subida solo se lee si se esperaba y hasta 2 GB; un tamaño no válido se rechaza.
- `X-Content-Type-Options: nosniff` y `Cache-Control: no-store`. El CORS abierto (`*`) es a propósito:
  la ventana se sirve desde otro puerto, y lo que protege el dato es el código.

### Instancia única (escritorio)

[`app/single_instance.py`](../../app/single_instance.py): la tubería es del usuario (en Linux, en su
carpeta de ejecución o personal, nunca en `/tmp`) y el mensaje es una lista de rutas en **JSON**, de
tamaño limitado. Antes se usaba `Connection.recv`, que deserializa con `pickle`: quien conectara
podía ejecutar código. Solo se abren rutas de archivos que existen.

### La clave de API del asistente

- En Windows se guarda **cifrada con DPAPI** ([`pdf_core/agent/keystore.py`](../../src/pdf_core/agent/keystore.py)):
  solo la descifra el mismo usuario en el mismo equipo. Una clave guardada en claro por una versión
  anterior se cifra la primera vez que se lee. En otros sistemas, el archivo solo lo lee su dueño
  (`0600`).
- El archivo se escribe de forma atómica (`config.py`).
- La clave nunca vuelve a la ventana (solo si hay una: `has_key`), y **se quita de los mensajes de
  error** antes de mostrarlos o registrarlos (algunos clientes la ponen en la URL de sus errores).

### Cifrar PDF

AES-256 (`security.protect`, motor de EmbedPDF). Sin contraseña de propietario se pone una aleatoria:
si estuviera vacía, cualquiera quitaría las restricciones.

### Procesos

Se lanzan sin shell y con listas de argumentos. «Mostrar en carpeta» usa la ruta completa de
`explorer.exe` (`%SystemRoot%`): sin ella, Windows buscaría también uno en la carpeta actual.

### La versión de navegador

- Todo se carga de la misma web: Python, sus paquetes, el motor PDF y los modelos del OCR. Nada de CDN
  al usarla. `installer/browser/prepare.py` comprueba la suma SHA-256 de cada paquete al bajarlo, en la
  versión fijada en `uv.lock`.
- Python y el OCR corren en *workers*: el wasm de cada uno, en su propio espacio.
- La página tiene que estar aislada (COOP/COEP) para que Python tenga memoria compartida
  (`lib/browser/protocol.ts`).
- **Al publicarla**, el servidor debería enviar estas cabeceras (`pnpm preview:web` ya lo hace, en
  `vite.config.ts`): `Cross-Origin-Opener-Policy: same-origin`,
  `Cross-Origin-Embedder-Policy: require-corp`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer` y, si puede, la misma CSP como cabecera con
  `frame-ancestors 'none'` (contra que otra web la meta en un marco; desde `<meta>` no se puede).

### Dependencias

- Versiones fijadas: `uv.lock` (Python) y `pnpm-lock.yaml` (interfaz).
- [`security.yml`](../../.github/workflows/security.yml) las audita en cada pull request, en cada
  push a `main` y cada lunes: `pip-audit` (Python) y `pnpm audit` (falla con avisos altos o críticos).

## Riesgos aceptados

| Riesgo | Por qué se acepta | Cuándo revisarlo |
|---|---|---|
| **Svelte 5.51.0** tiene avisos moderados (`pnpm audit`) | Está fijado porque desde 5.51.1 los clics sobre las anotaciones de EmbedPDF 2.15.1 no llegan (ver [embedpdf.md](embedpdf.md)). Casi todos los avisos son de renderizado en servidor (SSR), que la app no usa; el de «DOM clobbering» necesita colar HTML con `id`, y la app no pinta HTML de fuera (y la CSP no ejecutaría scripts) | Al actualizar EmbedPDF |
| `style-src 'unsafe-inline'` en la CSP | Svelte y EmbedPDF ponen estilos en atributos `style`. Un estilo no ejecuta código | Si Svelte deja de necesitarlo |
| La clave de API, en claro dentro del navegador (IndexedDB) | No hay almacén del sistema en una web; en el navegador el asistente funciona en modo básico (sin proveedor) | Si el navegador llega a usar un proveedor de IA |
| En GitHub Pages, sin `frame-ancestors` | No se pueden poner cabeceras. La app no tiene acciones de servidor que otra web pudiera provocar | Si se publica en un servidor con cabeceras |
| PDFium en el proceso de Python (escritorio) | No hay alternativa sin aislar en otro proceso; se mantiene actualizado (`pypdfium2`) | Con cada versión de `pypdfium2` |

## Pendiente (recomendado)

- **Firmar el instalador y el ejecutable** (Authenticode): sin firma, Windows SmartScreen avisa y no se
  puede comprobar que nadie lo modificó.
- **Avisar de contraseñas cortas al cifrar un PDF** (menos de 8 caracteres, como recomienda NIST
  800-63B): con AES-256, la contraseña es lo único débil.

## Cómo comprobarlo

- Python: `uv run pytest`; las de seguridad son `test_single_instance_never_unpickles_what_it_receives`,
  `test_byte_server_only_answers_its_own_address_and_limits_uploads`,
  `test_ai_keys_are_stored_encrypted_and_old_plain_keys_are_migrated`,
  `test_ai_errors_never_show_the_api_key` y `test_only_web_and_mail_links_open_outside`.
- La CSP: usar la app con la consola abierta y buscar «Content Security Policy». En las pruebas de
  extremo a extremo se recoge cada `securitypolicyviolation` mientras se abre un documento, se busca,
  se usan sellos, el OCR, el asistente, la Ayuda y se imprime (escritorio y navegador).
- Dependencias: `uvx pip-audit` y `pnpm audit` (o el workflow).
- Análisis estático: `uv run --with ruff ruff check app src/pdf_core --select S`. Quedan
  `try-except-pass` (limpiezas opcionales) y los comandos de desarrollo de `app/ui_dev.py`.
