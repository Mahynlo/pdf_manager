# Ejecutable e instalador de la versión web

```
.\installer\web\build.ps1                       # ejecutable + instalador
.\installer\web\build.ps1 -SkipInstaller        # solo el ejecutable
.\installer\web\build.ps1 -Version 0.1.29-web   # otra versión que la de app\__init__.py
```

1. **pnpm** compila la interfaz (`app\ui` → `app\ui\dist`, ver [svelte.md](svelte.md)).
   - Hace falta tener Node.js y pnpm instalados; si falta pnpm, el script se detiene.
2. **PyInstaller** genera `dist\web\ExtraerPDFs\`, con `ExtraerPDFs.exe` y su carpeta `_internal`.
   - Se ejecuta con `uv run --with pyinstaller`, así no hace falta añadirlo a las dependencias del proyecto.
   - No usa archivo `.spec` (están en `.gitignore`): las opciones están en el propio script.
3. **Inno Setup 6** compila `installer\web\setup.iss` en `dist\ExtraerPDFs_Web_Setup_<versión>.exe`.
   - La versión es `APP_VERSION` de `app\__init__.py` (también se ve en Ajustes). Va aparte de
     `pyproject.toml`, que lleva la de Flet y solo admite versiones PEP 440 (`0.1.29-web` no lo es).
   - Si Inno Setup no está instalado, el script indica el comando para compilarlo después.

`build\` y `dist\` están en `.gitignore`.

## Qué va dentro

| Recurso | Ruta en `_internal` | Lo usa |
|---|---|---|
| `app\ui\dist` | `app\ui\dist` | La ventana (`app.UI_DIST_DIR`) |
| `src\assets\ayuda`, `ayuda_img`, `ayuda_svg` | Las mismas | Pestaña Ayuda (`services/help.py`) |
| `src\assets\ocr_models` | `assets\ocr_models` | Modelos de OCR de PaddleOCR (`pdf_core/ocr/paddle.py` los busca dos carpetas por encima de su archivo) |
| Módulos de `pdf_core` | Dentro del ejecutable | Todo el backend |

Empaquetada, `app.PROJECT_ROOT` es la carpeta `_internal`, dentro de Archivos de programa, donde no se
puede escribir. Por eso lo que se escribe va siempre a la carpeta del usuario:
- preferencias, registro y datos de WebView2 en `~/.pdf_manager`;
- recientes, leyendas y perfiles en `~/.extraer_pdfs_*.json`;
- la carpeta de destino de «Extraer», que si no puede crear `storage\temp` usa «Documentos».

El ejecutable ocupa unos 189 MB. Lo que más pesa:
- los modelos de OCR (37 MB) y onnxruntime (32 MB);
- MuPDF (25 MB + 12 MB de PyMuPDF);
- la interfaz (5,6 MB), casi toda el motor PDFium del visor (`pdfium.wasm`, ver [embedpdf.md](embedpdf.md));
- NumPy con su OpenBLAS, que PyInstaller copia dos veces (en la raíz y en `numpy.libs`, 20 MB cada una):
  quitar el duplicado ahorraría otros 20 MB.

Antes ocupaba 420 MB: onnxtr arrastraba OpenCV (99 MB) y SciPy (~89 MB). El OCR ya no los usa
(ver [modulos-python.md](modulos-python.md)).

## «Abrir con» e instancia única

No hace falta el `launcher.exe` de la versión Flet: el ejecutable recibe las rutas como argumentos.
Las lee `pdf_core.launch_args`, que también acepta la variable `EXTRAR_PDF_PATH` del launcher.

Si ya hay una ventana abierta, `app/single_instance.py` le pasa los PDF por una tubería con nombre del
usuario y la nueva instancia sale; la ventana abre los PDF y pasa al frente.

El instalador registra:
- el ProgID `ExtraerPdfs.Web.PdfFile`;
- la entrada `Applications\ExtraerPDFs.exe`;
- las capacidades de la app;
- y, si se marca la tarea, la entrada en «Abrir con» de `.pdf`. No cambia el programa predeterminado.

## En GitHub Actions

`.github/workflows/build-web.yml` hace lo mismo en un runner de Windows (con Inno Setup, que allí sí
se instala):
- **tag `vX.Y.Z-web`** (p. ej. `v0.1.29-web`): compila, sube el instalador como artefacto y crea
  una Release marcada como prerelease. El tag tiene que coincidir con `APP_VERSION`, si no falla;
- **Actions → Run workflow**: solo el artefacto, sin Release.

El workflow de Flet (`build.yml`) sigue con los tags `vX.Y.Z` y no se dispara con los `-web`.

La versión Qt (`src_qt\`, `tests\test_qt_*.py`) no se sube: está en `.gitignore` y en la rama local
`feature/pyside-migration`. Las pruebas compartidas que la usan se saltan si no está.

## Convivencia con la versión Flet

El instalador web tiene otro `AppId`, otra carpeta (`Extraer PDFs Web`) y otro ProgID, así las dos
versiones se pueden instalar a la vez durante la transición.

Cuando la web sustituya a Flet en producción, hay dos opciones:
- usar en `installer\web\setup.iss` el `AppId` de `installer\setup.iss`, para que instalar la web actualice la instalación existente;
- desinstalar antes la versión Flet.

## Comprobado

- `build.ps1 -SkipInstaller` genera el ejecutable.
- El ejecutable arranca con un PDF como argumento y lo abre.
- Una segunda ejecución con otro PDF se lo pasa a la primera ventana y sale en menos de 1 s.
- Se cierra sin errores en el registro.
- El OCR y la corrección de orientación funcionan dentro del ejecutable (página de prueba: 165 palabras
  en 3,4 s; la página al revés se detecta y se gira 180°).
- El visor con EmbedPDF funciona igual que en desarrollo: carga `pdfium.wasm` desde el paquete, sin
  internet; tres PDF abiertos a la vez dibujan sus páginas; girar una página recarga el documento; cerrar
  la pestaña activa deja bien la siguiente. Sin errores de JavaScript.

Pendiente:
- compilar el instalador: lo hace el workflow `build-web.yml` (en el equipo de desarrollo no se instala Inno Setup);
- probar «Abrir con» desde el Explorador una vez instalado.
