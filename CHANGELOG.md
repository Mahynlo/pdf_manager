# Changelog

## [0.1.14] - 2026-05-31

### Changed
- **Visor escalable a documentos de cientos de páginas (virtualización del árbol de controles)**: cada página arranca como un *placeholder* liviano y su árbol pesado de controles (imagen, overlays de selección/anotación/OCR/censura, menús y `GestureDetector`) se construye bajo demanda al entrar en la ventana visible y se libera al alejarse. Antes se construían ~50 controles × N páginas al abrir el PDF (~40.000 para 800 páginas) → la carga se congelaba y la RAM se disparaba. Ahora abrir un PDF de 800 páginas es fluido y la RAM queda acotada a una ventana.
- **Selección de texto y arrastre de anotaciones fluidos en PDFs grandes**: la conversión de coordenadas viewport↔página (`_get_global_y` / `_get_page_and_local_y`) pasó de un barrido lineal O(N) por evento de arrastre a O(1)/O(log N) usando los offsets acumulados ya cacheados. Antes, seleccionar texto en la página 700 de 800 se sentía lento.
- **Scroll rápido sin hojas en blanco**: durante un *fling* rápido ahora se renderiza una vista previa de baja resolución (LOD) en vez de dejar la página en blanco; al detenerse se sube a calidad completa con *swap* sin parpadeo. El retardo de render tras detener el scroll bajó de 0.2 s a 0.1 s.
- **Atajos de zoom al estilo visor**: el zoom se activa con **Ctrl + `+`/`=` (acercar), `-` (alejar) y `0` (100%)** — una vez por pulsación, sin repetirse mientras se mantiene la tecla. Las teclas `+`/`-` a secas ya no hacen zoom (evita disparos accidentales). Nota: el zoom con **Ctrl+rueda** no es soportable de forma fiable en esta versión de Flet (el evento de scroll no incluye el modificador Ctrl y mantener solo Ctrl no emite evento de teclado), por lo que la rueda siempre hace scroll.

### Fixed
- **El visor perdía la página al cambiar de pestaña**: al volver a un PDF (desde otra pestaña, inicio, etc.) el scroll saltaba al inicio en vez de mantener la hoja en la que estabas. Ahora `on_focus` restaura la posición exacta de scroll.
- **`AttributeError: 'NoneType'` en selección de texto / panel OCR**: caminos de la GUI que recorrían las listas por página no toleraban los *slots* no construidos (placeholders) introducidos por la virtualización.
- **Ctrl+A / Ctrl+Z disparaban el zoom**: tras un atajo Ctrl+letra, un scroll inmediato con la rueda hacía zoom por error (Flet no emite *keyup*, así que el estado de Ctrl quedaba "pegado" durante ~1 s). Ahora cualquier atajo Ctrl+letra desarma el zoom-rueda explícitamente.

## [0.1.13] - 2026-05-21

### Changed
- **Módulo de agente IA refactorizado**: `_redact_agent_mixin.py` (~2100 líneas) se dividió en tres módulos independientes: `_redact_mixin.py` (búsqueda, términos, vista previa y aplicación de censura), `_profiles_mixin.py` (diálogos de gestión de perfiles de censura) y `_agent_mixin.py` (panel de chat y acciones rápidas del agente IA).

## [0.1.12] - 2026-05-21

### Added
- **Atajos de teclado completos en el visor**: Ctrl+Z (deshacer), Ctrl+A (seleccionar todo el texto), Ctrl+S (guardar), Ctrl+P (imprimir), Ctrl+C (copiar selección), Ctrl+O (abrir archivo), Ctrl+Inicio/Fin (ir a primera/última página), Escape (deseleccionar), Inicio/Fin, flechas, Re Pág/Av Pág, `+`/`-` (zoom), `W` (ajustar ancho), `F` (ajustar página).

### Changed
- **Vista previa de impresión rediseñada**: Las páginas ahora se muestran como una lista vertical desplazable (estilo filmstrip) con miniatura a la izquierda e información de página a la derecha, en lugar de una cuadrícula envuelta.
- **Apertura de archivos recientes más rápida**: Los módulos `pdf_viewer` y `pdf_security` se pre-cargan en segundo plano al iniciar la app, eliminando el retardo en el primer clic.

### Fixed
- **Doble apertura de archivos recientes**: Se agregó un guard `_opening_now` que previene abrir el mismo PDF dos veces si el usuario hace clic rápidamente o doble clic.
- **Ctrl+Scroll no se desactiva**: El modo zoom con Ctrl+Scroll ya no queda "pegado" después de soltar Ctrl. Ahora expira automáticamente en 1 segundo, restaurando el scroll normal sin necesidad de presionar otra tecla.

## [0.1.11] - 2026-05-20

### Changed
- **Manejo de instancia única en Windows mejorado**: La ventana se oculta antes de que Flutter la muestre al usuario, eliminando el parpadeo de ventana huérfana cuando la app ya está en ejecución.
- **IPC y conexión TCP optimizados**: Mejoras en el manejo de rutas iniciales y la conexión TCP en Windows para mayor fiabilidad al abrir PDFs con "Abrir con".

### Fixed
- Error de tipo en la firma de `_close_viewer_tab`.

## [0.1.10] - 2026-05-19

### Fixed
- Correcciones en el manejo de "Abrir con" y empaquetado en Windows.
- Mejoras en la compatibilidad de rutas y en la inicialización del IPC al usar `flet build`.

## [0.1.9] - 2026-05-19

### Changed
- **Eliminación de dependencias críticas**: Se removieron por completo los módulos de `pywin32` para solucionar conflictos en el empaquetado con `flet build windows` y garantizar la compatibilidad multiplataforma en Linux y macOS.
- **Rediseño de Instancia Única (IPC)**: Se migró la lógica en `main.py` hacia una solución nativa basada en sockets TCP locales combinados con un archivo de bloqueo (*lockfile*).
- **Módulo de Impresión Portátil**: Se reestructuró la lógica de impresión utilizando utilidades nativas de cada sistema operativo (PowerShell en Windows, y CUPS en Linux y macOS) en lugar de llamadas a la API de Windows.

## [0.1.8] - 2026-05-18

### Changed
- Se actualizaron los imports de pywin32 a nivel explícito para garantizar que flet build los detecte correctamente.
- Se movieron imports de win32print, win32ui, win32con desde imports dinámicos a explícitos en _print_mixin.py.

## [0.1.8] - 2026-05-18

### Changed
- Se publicó una nueva versión de release con la configuración de build ya alineada.

## [0.1.7] - 2026-05-18

### Changed
- Se agregó `pywin32` al bundle de Windows para que la detección de impresoras e IPC funcionen en producción.
- Se alineó la versión del instalador y del paquete con el release 0.1.7.

## [0.1.6] - 2026-05-18

### Added
- Notificaciones visuales de estado y errores para operaciones de impresión en el visor.
- Guardado explícito desde la app para impresoras PDF virtuales (por ejemplo "Microsoft Print to PDF").

### Changed
- Flujo de impresión mejorado: la app usa `FilePicker` para impresoras interactivas y evita bloquear la UI.
- Integración de impresión en Windows más robusta (soporte GDI directo cuando está disponible).

### Fixed
- Correcciones en el manejo del `FilePicker` para que los diálogos se muestren correctamente.

## [0.1.5] - 2026-05-15

### Added
- Apertura de PDFs desde el sistema operativo con soporte para "Abrir con" y reenvío a la ventana ya abierta.
- Comportamiento de instancia única para evitar que se abra otra ventana al lanzar un PDF cuando la app ya está en ejecución.
 - Mejoras en la selección de texto y en las herramientas de anotación: subrayado y tachado más precisos y fiables.

- Reanudación de extracción con PDFs protegidos en secuencias de múltiples archivos.

### Changed
 - Mejoras visuales en el visor: renderizado y estilos de anotaciones actualizados para mayor legibilidad.
- La extracción y la combinación de PDFs respetan mejor los documentos protegidos y mantienen la navegación en pestañas existentes.
- El instalador Inno Setup registra la asociación de `.pdf` para que la app aparezca como opción en "Abrir con".

### Fixed
- Corrección del flujo al abrir PDFs protegidos desde la integración del sistema operativo.
- Ajustes para continuar la extracción cuando hay más de un PDF protegido en el lote.

## [0.1.4] - 2026-05-14

### Changed
- Ajustes en seguridad de PDFs: ahora se utiliza `doc.save(..., encryption=...)` para crear PDFs protegidos, mejor compatibilidad con PyMuPDF.
- La pestaña `Seguridad` muestra los permisos reales del documento después de desbloquear.
- `remove_protection` ahora genera una copia sin cifrado de forma segura.

### Fixed
- Correcciones menores en la gestión de visibilidad de la UI para mostrar información de seguridad.

