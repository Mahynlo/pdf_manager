// Textos comunes: botones y diálogos de lib/ que usan todas las herramientas.

export default {
  cancel: 'Cancelar',
  accept: 'Aceptar',
  yes: 'Sí',
  no: 'No',
  close: 'Cerrar',
  /** Contraseña de un PDF (PasswordDialog.svelte, askPassword). */
  password: {
    title: 'PDF protegido',
    needed: (name: string) => `«${name}» necesita contraseña para abrirse.`,
    placeholder: 'Contraseña',
    unlock: 'Desbloquear',
    show: 'Mostrar contraseña',
    hide: 'Ocultar contraseña',
  },
};
