// Creación de elementos para el código imperativo del lienzo del visor (capas de texto,
// anotaciones y sus barras flotantes), que se actualiza a mano por rendimiento. Las
// pantallas se escriben como componentes Svelte; esto es solo para ese código.
//
// Sin innerHTML: los textos (nombres de archivo, rutas…) siempre entran como nodos de texto.
//
//   h('button', { class: 'btn', onclick: save, disabled: true }, ic('save'), 'Guardar')

/** Hijos de h(): nodos, textos o listas de ellos; null, undefined y false se saltan. */
export type Child = Node | string | null | undefined | false | Child[];

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Record<string, any> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style') for (const [prop, v] of Object.entries(value)) el.style.setProperty(prop, String(v));
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'value' || typeof value !== 'string') (el as any)[key] = value; // propiedades: value, checked, disabled…
    else el.setAttribute(key, value);
  }
  el.append(...flatten(children));
  return el;
}

/** Los hijos en una sola lista, sin los vacíos. */
function flatten(children: Child[], out: (Node | string)[] = []): (Node | string)[] {
  for (const child of children) {
    if (Array.isArray(child)) flatten(child, out);
    else if (child != null && child !== false) out.push(child);
  }
  return out;
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}
