# Changelog

## [0.1.5] - 2026-05-15

### Added
- Apertura de PDFs desde el sistema operativo con soporte para "Abrir con" y reenvío a la ventana ya abierta.
- Comportamiento de instancia única para evitar que se abra otra ventana al lanzar un PDF cuando la app ya está en ejecución.
- Reanudación de extracción con PDFs protegidos en secuencias de múltiples archivos.

### Changed
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

