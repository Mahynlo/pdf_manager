// Paneles emergentes bajo un botón (el selector de color, el de grosor…): como un menú, pero con
// un componente dentro. Solo hay uno abierto a la vez; lo pinta Popover.svelte (en App.svelte).
// Se cierra con Esc, con un clic fuera o con closePopover(); pulsar otra vez su botón también.
//
//   openPopover(button, ColorPanel, { value: '#FF0000', onPick: (color) => … });
import type { Component } from 'svelte';

export const popover = $state<{ component: Component<any> | null; props: Record<string, unknown>; anchor: Element | null }>({
  component: null, // null: cerrado
  props: {},
  anchor: null,
});

export function closePopover(): void {
  popover.component = null;
  popover.anchor = null;
}

/** Abre `component` con `props` bajo `anchor`; si ya estaba abierto en ese botón, lo cierra. */
export function openPopover<P extends Record<string, any>>(anchor: Element, component: Component<P>, props: P): void {
  if (popover.anchor === anchor) {
    closePopover();
    return;
  }
  Object.assign(popover, { component, props, anchor });
}

/** ¿Está abierto un panel de un botón de dentro de `container`? */
export function popoverIn(container: Element): boolean {
  return Boolean(popover.anchor && container.contains(popover.anchor));
}
