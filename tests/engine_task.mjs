// Motor de EmbedPDF para las pruebas de Python (tests/pdfkit.py): hace una tarea sobre un PDF con
// el mismo código y el mismo PDFium que la ventana.
//
//   node engine_task.mjs <tarea> <args JSON> <entrada.pdf> <salida.pdf>
//
// Además de las de engine-tasks.ts tiene las que en la app hace el visor: poner marcas de censura
// (como redaction.ts), escribir metadatos y cambiar las páginas (como document/pages.ts, con el
// mismo motor: lib/pdf-engine/native.ts).
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ui = path.join(root, 'app', 'ui');
const modules = path.join(ui, 'node_modules', '@embedpdf');
const url = (file) => pathToFileURL(file).href;

const { init } = await import(url(path.join(modules, 'pdfium', 'dist', 'index.js')));
const { AppNative } = await import(url(path.join(ui, 'src', 'lib', 'pdf-engine', 'native.ts')));
const { PdfAnnotationSubtype } = await import(url(path.join(modules, 'models', 'dist', 'index.js')));
const { runTask } = await import(url(path.join(ui, 'src', 'lib', 'engine-tasks.ts')));

const [task, rawArgs, input, output] = process.argv.slice(2);
const args = JSON.parse(rawArgs);
const wasm = fs.readFileSync(path.join(modules, 'pdfium', 'dist', 'pdfium.wasm'));
const pdfium = await init({ wasmBinary: wasm.buffer.slice(wasm.byteOffset, wasm.byteOffset + wasm.byteLength) });
pdfium.PDFiumExt_Init();
const engine = new AppNative(pdfium);

const file = fs.readFileSync(input);
const buffer = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength);

/** Las tareas que aquí hace el visor: abrir, cambiar y guardar. */
async function edit(change) {
  const doc = await engine.openDocumentBuffer({ id: 'test', content: buffer }, { password: args.password ?? undefined, normalizeRotation: true }).toPromise();
  await change(doc);
  const saved = await engine.saveAsCopy(doc).toPromise();
  await engine.closeDocument(doc).toPromise();
  return saved;
}

function mark(doc, { page, rect: [x0, y0, x1, y1], color }, index) {
  const box = { origin: { x: x0, y: y0 }, size: { width: x1 - x0, height: y1 - y0 } };
  return engine.createPageAnnotation(doc, doc.pages[page], {
    type: PdfAnnotationSubtype.REDACT, id: `marca-${index}`, pageIndex: page, rect: box, segmentRects: [box],
    color, overlayColor: color, strokeColor: '#E53935', opacity: 1, flags: ['print'],
  }).toPromise();
}

let result;
if (task === 'mark') {
  result = await edit(async (doc) => {
    for (const [index, item] of args.marks.entries()) await mark(doc, item, index);
  });
} else if (task === 'meta') {
  result = await edit((doc) => engine.setMetadata(doc, args.metadata).toPromise());
} else if (task === 'pages') {
  // args.ops: [operación, ...argumentos] en orden; 'remove-restore' borra una página y la
  // devuelve desde su copia guardada (deshacer un borrado).
  result = await edit((doc) => {
    for (const [op, ...rest] of args.ops) {
      if (op === 'rotate') engine.rotatePages(doc, ...rest);
      else if (op === 'move') engine.movePage(doc, ...rest);
      else if (op === 'remove') engine.removePage(doc, ...rest);
      else if (op === 'blank') engine.insertBlankPage(doc, ...rest);
      else if (op === 'duplicate') engine.duplicatePage(doc, ...rest);
      else if (op === 'remove-restore') {
        const stash = engine.stashPage(doc, rest[0]);
        engine.removePage(doc, rest[0]);
        engine.restorePages(doc, stash, rest[0]);
        engine.dropStash(stash);
      } else throw new Error(`Operación desconocida: ${op}`);
    }
  });
} else if (task === 'copy' || task === 'extract') {
  // Las copias que saca el visor (como document/copy.ts): args.withoutText, args.decrypt y,
  // para extraer, args.indices.
  const doc = await engine.openDocumentBuffer({ id: 'test', content: buffer }, { password: args.password ?? undefined, normalizeRotation: true }).toPromise();
  result = task === 'copy'
    ? engine.saveCopy(doc, { withoutText: args.withoutText, decrypt: args.decrypt, password: args.password })
    : engine.extractCopy(doc, args.indices, args.withoutText);
  await engine.closeDocument(doc).toPromise();
} else if (task === 'facts') {
  const doc = await engine.openDocumentBuffer({ id: 'test', content: buffer }, { password: args.password ?? undefined }).toPromise();
  result = new TextEncoder().encode(JSON.stringify(engine.documentFacts(doc)));
  await engine.closeDocument(doc).toPromise();
} else {
  result = await runTask(engine, task, buffer, args);
}
fs.writeFileSync(output, Buffer.from(result));
