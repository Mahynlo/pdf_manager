// Arrastrar PDFs desde el Explorador a la ventana (como dropEvent de la ventana Qt).
// El navegador no da la ruta de un archivo soltado: la recibe la ventana pywebview
// (WebviewHost), que abre los PDF. Aquí solo se evita que WebView2 navegue al archivo
// y se muestra el aviso «Suelta…» mientras se arrastra.
//
// Solo cuentan los arrastres de archivos: mover miniaturas (visor, combinar) no.
const hasFiles = (ev) => Array.from(ev.dataTransfer?.types ?? []).includes('Files');

export function enableFileDrop() {
  let depth = 0; // dragenter/dragleave llegan por cada elemento que se cruza
  const show = (on) => document.body.classList.toggle('is-dropping', on);
  document.addEventListener('dragenter', (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    depth++;
    show(true);
  });
  document.addEventListener('dragover', (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault(); // sin esto no hay «drop» y WebView2 abriría el archivo
    ev.dataTransfer.dropEffect = 'copy';
  });
  document.addEventListener('dragleave', (ev) => {
    if (!hasFiles(ev)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) show(false);
  });
  document.addEventListener('drop', (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    depth = 0;
    show(false);
  });
}
