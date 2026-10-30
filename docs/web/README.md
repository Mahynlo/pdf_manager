# Versión web

Interfaz en **Svelte** (`app/ui`, compilada con Vite) y backend en **Python**, unidos por pywebview
(WebView2 en Windows). El visor dibuja los PDF con **EmbedPDF** (motor PDFium en el navegador). Es la versión definitiva: sustituirá a Flet en producción. Las funciones se están
trayendo desde la versión Qt (`src_qt/`), que sirve de referencia.

```
uv run python -m app.main            # arrancar (recompila la interfaz si cambió)
uv run python -m app.main --dev      # con el servidor de Vite: recarga al guardar
uv run python -m app.main --debug    # con herramientas de desarrollo (F12)
uv run pytest tests/test_app_backend.py tests/test_web_architecture.py
```

## Documentos

| Documento | Contenido |
|---|---|
| [arquitectura.md](arquitectura.md) | Estructura de `app/`, comunicación JS ↔ Python, reglas y cómo migrar una herramienta |
| [modulos-python.md](modulos-python.md) | Módulos de Python que usa la web (`src/pdf_core`), reglas y plan de retirada de Qt y Flet |
| [paridad.md](paridad.md) | Lista función por función de la versión Qt y su estado en la web |
| [instalador.md](instalador.md) | Ejecutable (PyInstaller), instalador (Inno Setup), «Abrir con» e instancia única |
| [svelte.md](svelte.md) | La interfaz en Svelte (`app/ui`): estructura, compilación y cómo escribir componentes |
| [embedpdf.md](embedpdf.md) | Migración del visor a EmbedPDF paso a paso: plan, estado y cómo está hecho cada paso |

## Estado

### Terminado

- **Ventana y pestañas**:
  - Inicio fija, una pestaña por herramienta y una por PDF, menú de marca, tema claro/oscuro;
  - atajos y barra de estado;
  - aviso de cambios sin guardar al cerrar una pestaña o la ventana.
- **Inicio**: herramientas y archivos recientes (compartidos con Flet y Qt).
- **Combinar, Seguridad y Extraer**: completas, con trabajos en segundo plano, contraseñas y progreso.
- **Ajustes y Ayuda**: tema, recientes, registro de diagnóstico, atajos y manuales.
- **Visor de PDF** (páginas dibujadas por EmbedPDF; migración en curso, ver [embedpdf.md](embedpdf.md)):
  - Lectura: zoom, modos de vista, navegación, miniaturas, índice, modo noche.
  - Páginas: rotar, mover (también arrastrando miniaturas), duplicar, insertar, eliminar y extraer.
  - Guardado: guardar y guardar como; un PDF cifrado conserva su contraseña.
  - Texto: selección con EmbedPDF (también entre páginas; palabra con doble clic, línea con triple), copiar y búsqueda con resultados.
  - Anotaciones:
    - resaltar, subrayar, tachar;
    - rectángulo, círculo, flecha, pluma;
    - texto libre, notas, sellos y leyendas guardadas;
    - edición con el puntero: mover, redimensionar, color, grosor, relleno, orden, duplicar;
    - deshacer y rehacer.
  - OCR: página actual, recorte y lotes, con métricas y cajas en el lienzo; el texto reconocido se
    selecciona, se busca y se exporta. Corrección de orientación (una página o todas).
  - Censura: términos, patrones de datos personales, selecciones, áreas marcadas a mano y perfiles
    guardados; cada coincidencia es una marca que se revisa en la página antes de la aplicación
    irreversible (solo se guarda como copia).
  - Imprimir: páginas, orden inverso, orientación, color y escala con vista previa; impresora,
    copias y doble cara en el diálogo del sistema.
  - Asistente IA: chat, resumen, datos clave y datos sensibles (que se envían a «Censura»). Sin
    las dependencias del agente ni clave de API responde en modo básico.
  - Exportar: texto e imágenes.

- **Sistema**: arrastrar y soltar PDFs, instancia única y «Abrir con» (el ejecutable recibe las rutas).
- **Distribución**: ejecutable con PyInstaller (`installer/web/build.ps1`), comprobado con el visor EmbedPDF.

### Pendiente

- **Visor con EmbedPDF**: paso 4 (herramientas); ver [embedpdf.md](embedpdf.md).
- **Instalador**: compilarlo con Inno Setup y probar el ejecutable instalado: OCR, «Abrir con» desde
  el Explorador y arrastrar archivos desde el Explorador.
- **Asistente IA con agente**: instalar sus dependencias (comentadas en `pyproject.toml`); sin ellas
  responde en modo básico.

El detalle de cada función, con las diferencias respecto a Qt, está en [paridad.md](paridad.md).
