// Menús emergentes (como QMenu): bajo un botón o en la posición del clic derecho.
// Solo hay uno abierto a la vez; lo pinta Menu.svelte (en App.svelte).
//
//   openMenu(ev.currentTarget, [
//     { label: 'Abrir', icon: 'folder-open', onSelect: abrir },
//     'separator',
//     { label: 'Quitar', icon: 'x', checked: false, disabled: false, onSelect: quitar },
//   ]);

export const menu = $state({
  items: null, // null: cerrado
  x: 0,
  y: 0,
  anchor: null, // DOMRect del botón (para alinearlo a su derecha si no cabe)
});

export function closeMenu() {
  menu.items = null;
}

/** Muestra el menú en (x, y); Menu.svelte lo mantiene dentro de la ventana. */
export function openMenuAt(x, y, items) {
  Object.assign(menu, { items, x, y, anchor: null });
}

/** Muestra el menú bajo `anchor` (alineado a su izquierda, o a su derecha si no cabe). */
export function openMenu(anchor, items) {
  const box = anchor.getBoundingClientRect();
  Object.assign(menu, { items, x: box.left, y: box.bottom + 4, anchor: box });
}
