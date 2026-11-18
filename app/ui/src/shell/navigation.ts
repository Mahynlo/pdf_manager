// La ventana nunca sale de la app. En el escritorio, una página externa cargada en la ventana
// recibiría el puente con Python (pywebview lo inyecta en lo que se cargue) y podría leer y escribir
// archivos: por eso ningún enlace ni nada que se suelte la lleva a otra dirección. Los enlaces se
// abren en el navegador del sistema (`app.open_url`, que solo deja http, https y mailto).
// Ver docs/web/seguridad.md.
import { call } from '$lib/api.ts';

const isLinkDrag = (ev: DragEvent) => {
  const types = Array.from(ev.dataTransfer?.types ?? []);
  return types.includes('text/uri-list') && !types.includes('Files'); // los archivos: dropzone.ts
};

export function guardNavigation(): void {
  // Clic, clic central o con Ctrl/Mayús en un enlace: nunca dentro de la ventana ni en otra ventana.
  const onLink = (ev: MouseEvent) => {
    const link = (ev.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
    if (!link || ev.defaultPrevented) return;
    const url = new URL(link.href, location.href);
    if (url.origin === location.origin && url.pathname === location.pathname && url.hash) return; // ancla en la página
    ev.preventDefault();
    if (ev.type === 'click' || ev.button === 1) void call('app.open_url', url.href);
  };
  document.addEventListener('click', onLink);
  document.addEventListener('auxclick', onLink);

  // Soltar un enlace (arrastrado desde el navegador) no lleva la ventana a esa página. Lo que
  // aceptan los componentes (ya marcado con preventDefault) sigue igual.
  document.addEventListener('dragover', (ev) => {
    if (!isLinkDrag(ev) || ev.defaultPrevented) return;
    ev.preventDefault();
    ev.dataTransfer!.dropEffect = 'none';
  });
  document.addEventListener('drop', (ev) => {
    if (isLinkDrag(ev) && !ev.defaultPrevented) ev.preventDefault();
  });
}
