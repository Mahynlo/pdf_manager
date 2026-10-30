// Textos de «Información general» de Ayuda (los mismos que la versión Qt).
// Cada fila: [emoji, título, descripción].

export const GETTING_STARTED = [
  ['📂', 'Abrir un PDF',
    'Haz clic en el menú ☰ → «Abrir PDF» o presiona Ctrl+O. '
    + 'También puedes arrastrar un archivo PDF directamente a la ventana.'],
  ['↔️', 'Navegar páginas', 'Usa las flechas ↑ ↓, las teclas Re Pág / Av Pág, o el panel lateral de miniaturas.'],
  ['🔍', 'Zoom',
    'Ctrl + rueda del ratón para zoom continuo. Ctrl+= para acercar, Ctrl+− para alejar, Ctrl+0 para zoom 100 %. '
    + 'Ctrl+H ajusta a la página; Ctrl+W ajusta al ancho.'],
  ['💾', 'Guardar cambios',
    'Ctrl+S sobreescribe el archivo original con tus anotaciones y censuras. '
    + 'El menú de herramientas incluye «Guardar PDF como…» para crear una copia.'],
];

export const TOOLS_HELP = [
  ['✏️', 'Anotaciones y Dibujo',
    'Resalta texto, subraya, tacha, añade notas y dibuja formas geométricas directamente sobre el PDF. '
    + 'Deshacer/rehacer con Ctrl+Z / Ctrl+Y.'],
  ['✂️', 'Extraer texto',
    'Extrae palabras clave u OCR de uno o varios PDFs a la vez, incluso de archivos protegidos con contraseña.'],
  ['📑', 'Combinar PDFs',
    'Une múltiples PDFs en un solo documento. Reordena las páginas arrastrando las miniaturas antes de combinar.'],
  ['🔒', 'Seguridad y Cifrado',
    'Protege un PDF con contraseña AES-256, define permisos de impresión o desbloquea un documento para verlo.'],
  ['🔎', 'Buscar en el documento',
    'Presiona Ctrl+F dentro del visor para buscar texto. Navega entre coincidencias con las flechas ↑ ↓.'],
  ['⬛', 'Censurar / Redactar',
    'Selecciona regiones o texto sensible y aplica redacción permanente. '
    + 'El contenido censurado no se puede recuperar una vez guardado.'],
];

// [pregunta, respuesta]
export const FAQ = [
  ['¿Puedo abrir un PDF protegido con contraseña?',
    'Sí. Al abrirlo, la aplicación pedirá la contraseña automáticamente. '
    + 'Las operaciones que requieren permisos de propietario necesitan la clave de propietario.'],
  ['¿Dónde se guardan las anotaciones?',
    'Las anotaciones se guardan dentro del propio archivo PDF al usar Guardar (Ctrl+S) o Guardar como. '
    + 'No requiere archivos externos.'],
  ['¿La OCR funciona sin conexión a internet?',
    'Sí. La OCR usa un modelo local que se ejecuta en tu equipo. No se envían datos a ningún servidor externo.'],
  ['¿Puedo abrir varios PDFs a la vez?',
    'Sí. Cada PDF se abre en su propia pestaña. Usa el botón ➕ de la barra superior o Ctrl+O para abrir más documentos.'],
];
