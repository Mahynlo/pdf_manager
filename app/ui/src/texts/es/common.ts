// Textos comunes: botones y diálogos de lib/ que usan todas las herramientas.

export default {
  cancel: 'Cancelar',
  accept: 'Aceptar',
  yes: 'Sí',
  no: 'No',
  close: 'Cerrar',
  uploadError: (status: number) => `No se pudo pasar el archivo a Python (${status})`,
  /** Contraseña de un PDF (PasswordDialog.svelte, askPassword). */
  password: {
    title: 'PDF protegido',
    needed: (name: string) => `«${name}» necesita contraseña para abrirse.`,
    placeholder: 'Contraseña',
    unlock: 'Desbloquear',
    show: 'Mostrar contraseña',
    /** Contraseñas nuevas para cifrar un PDF (lib/passwords.ts). */
    problems: {
      invisible: 'Tiene caracteres de control o invisibles. Escríbela de nuevo sin pegarla.',
      symbols: 'Sin emojis ni símbolos especiales: otros lectores de PDF no podrían abrirlo.',
      normalized: 'Tiene espacios especiales o letras de ancho completo, que otros lectores leen distinto.',
      long: (bytes: number) => `Demasiado larga: como mucho ${bytes} bytes (unos 100 caracteres).`,
    },
    hide: 'Ocultar contraseña',
  },
};
