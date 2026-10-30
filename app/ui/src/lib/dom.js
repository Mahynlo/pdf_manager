// Creación de elementos para el código imperativo del lienzo del visor (capas de texto,
// anotaciones y sus barras flotantes), que se actualiza a mano por rendimiento. Las
// pantallas se escriben como componentes Svelte; esto es solo para ese código.
//
// Sin innerHTML: los textos (nombres de archivo, rutas…) siempre entran como nodos de texto.
//
//   h('button', { class: 'btn', onclick: save, disabled: true }, ic('save'), 'Guardar')

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style') for (const [prop, v] of Object.entries(value)) el.style.setProperty(prop, v);
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'value' || typeof value !== 'string') el[key] = value; // propiedades: value, checked, disabled…
    else el.setAttribute(key, value);
  }
  el.append(...children.flat(Infinity).filter((c) => c != null && c !== false));
  return el;
}

export function fileName(path) {
  return path.split(/[\\/]/).pop();
}
