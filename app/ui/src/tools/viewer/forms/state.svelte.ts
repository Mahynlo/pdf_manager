// Opciones de los formularios que comparten la barra (toolbars/FormsBar.svelte) y el panel de todos los
// visores; las lee annotations.ts al crear un campo.
export const formOptions = $state({
  keepTool: false, // «Crear varios seguidos»: tras crear un campo sigue la herramienta (si no, «Editar campos»)
});
