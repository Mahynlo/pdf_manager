# Changelog

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

