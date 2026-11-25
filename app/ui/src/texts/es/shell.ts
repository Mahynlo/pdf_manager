// Textos de la ventana principal (App.svelte, shell/): cabecera, pestañas, Inicio y arranque.

export default {
  /** Arranque (main.ts), antes de que exista la ventana. */
  boot: {
    waiting: 'Esperando al backend de Python… Esta interfaz se abre desde la app: '
      + 'ejecuta «uv run python -m app.main --dev» desde la raíz del proyecto.',
    /** Pasos de la pantalla de carga, en orden (`boot:progress`). */
    steps: ['Preparando el entorno…', 'Cargando el motor de PDF…', 'Abriendo la aplicación…'],
    privacy: 'Tus PDF se procesan en este equipo: no se suben a ningún servidor.',
    notIsolated: 'Esta página necesita las cabeceras COOP y COEP para usar memoria compartida.',
    failed: (message: string) => `Error al iniciar la interfaz: ${message}`,
  },
  header: {
    appName: 'Extraer PDFs',
    brandMenu: 'Menú de la aplicación',
    tabs: 'Pestañas abiertas',
    closeTab: { label: 'Cerrar pestaña', shortcut: 'Ctrl+F4' },
    openPdf: { label: 'Abrir PDF o imágenes', shortcut: 'Ctrl+O' },
    tabsList: 'Lista de pestañas abiertas',
    scrollTabsStart: 'Ver las pestañas anteriores',
    scrollTabsEnd: 'Ver las pestañas siguientes',
    theme: 'Cambiar tema claro / oscuro',
  },
  /** Menú de la marca (shell.brandMenu); los nombres de las herramientas están en `tools`. */
  brand: {
    openPdf: 'Abrir PDF o imágenes (Ctrl+O)',
    imagesToPdf: 'Imágenes a PDF…',
    theme: 'Alternar tema claro / oscuro',
  },
  /** Menú contextual de una pestaña. */
  tab: {
    close: 'Cerrar pestaña',
    closeOthers: 'Cerrar las otras pestañas',
    closeRight: 'Cerrar pestañas a la derecha',
    moveLeft: 'Mover a la izquierda (Ctrl+Shift+Re Pág)',
    moveRight: 'Mover a la derecha (Ctrl+Shift+Av Pág)',
    copyPath: 'Copiar ruta del archivo',
    pathCopied: 'Ruta copiada al portapapeles',
    reveal: 'Abrir carpeta en el Explorador',
  },
  /** Barra de estado (lib/feedback.svelte.ts): lo que muestra cuando no hay ningún mensaje. */
  status: { idle: 'Listo • Extraer PDFs' },
  /** Si el instalador no llevaba los modelos del OCR, se descargan la primera vez (evento ocr:download). */
  ocrDownload: {
    start: (megabytes: number) => `Descargando los modelos de OCR (${megabytes} MB). Solo hace falta la primera vez.`,
    progress: (percent: number) => `Descargando modelos de OCR… ${percent} %`,
    done: 'Modelos de OCR descargados',
  },
  opened: (name: string) => `Abierto: ${name}`,
  /** La dirección de la página es la de un documento que ya no está abierto (al recargar, o atrás). */
  reopen: (name: string) => `${name} ya no está abierto: ábrelo de nuevo para verlo.`,
  openFailed: (tool: string, message: string) => `No se pudo abrir ${tool}: ${message}`,
  /** Al cerrar la ventana con cambios sin guardar o trabajos en curso. */
  quit: {
    unsavedTitle: 'Archivos sin guardar',
    jobsTitle: 'Trabajo en curso',
    unsaved: (list: string) => `Los siguientes documentos tienen cambios sin guardar:\n\n${list}`,
    jobs: (list: string) => `Se cancelarán los trabajos en curso:\n\n${list}`,
    question: '¿Cerrar la aplicación de todos modos?',
  },
  home: {
    title: 'Inicio',
    local: 'Todo se procesa en tu equipo',
    localTip: 'Tus documentos no se suben a ningún servidor',
    heading: '¿Qué quieres hacer hoy?',
    lead: 'Abre un documento o elige una herramienta para empezar.',
    /** Zona para abrir o soltar archivos. */
    open: {
      title: 'Abrir un documento',
      text: 'Arrastra aquí un PDF o imágenes, o pulsa',
      touch: 'Elige un PDF o imágenes para verlos y editarlos.',
      button: 'Abrir archivo',
      formats: ['PDF', 'PNG', 'JPG', 'WEBP'],
    },
    tools: 'Herramientas',
  },
  recent: {
    title: 'Archivos recientes',
    clear: 'Limpiar',
    empty: 'Sin archivos recientes',
    remove: 'Quitar de recientes',
    menu: {
      open: 'Abrir documento',
      reveal: 'Abrir ubicación en Explorador',
      copyPath: 'Copiar ruta del archivo',
      remove: 'Quitar de la lista',
    },
  },
  /**
   * Nombres de las herramientas (shell/tools.ts): `title` en la pestaña, `menuLabel` en el menú
   * de la marca y `card` en Inicio (sin tarjeta no sale en Inicio).
   */
  tools: {
    extract: {
      title: 'Extraer',
      menuLabel: 'Extraer texto',
      card: { title: 'Extraer texto de PDF', text: 'Busca en muchos PDF a la vez las páginas que mencionan algo y júntalas.' },
    },
    merge: {
      title: 'Combinar',
      menuLabel: 'Combinar PDFs',
      card: { title: 'Combinar PDFs', text: 'Une varios PDF en uno, eligiendo qué páginas entran y en qué orden.' },
    },
    security: {
      title: 'Seguridad',
      menuLabel: 'Seguridad',
      card: { title: 'Gestión de Seguridad', text: 'Protege un PDF con contraseña y permisos, o quítale la protección.' },
    },
    settings: { title: 'Ajustes', menuLabel: 'Configuración' },
    help: { title: 'Ayuda', menuLabel: 'Ayuda' },
  },
  /** Tarjetas de Inicio que hacen una acción en vez de abrir una herramienta. */
  actions: {
    openPdf: { title: 'OCR de PDF', text: 'Abre un escaneo y reconoce su texto para buscarlo y copiarlo.' },
    imagesToPdf: { title: 'Imágenes a PDF', text: 'Convierte fotos y escaneos en un documento PDF.' },
  },
};
