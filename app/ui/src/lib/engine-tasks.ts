// Lo que el PDFium de Python no sabe hacer y hace el motor de EmbedPDF: cifrar y escribir
// marcadores. Python pide la tarea (Host.run_engine) con el PDF y recibe el PDF cambiado. (La
// censura la hace el visor en su documento: tools/viewer/redact/apply.ts.)
// Sin dependencias, para probarlo con el motor real en las pruebas de Python (tests/engine_task.mjs).

/** Lo que se usa del motor: cada llamada devuelve una tarea con `toPromise()`. */
interface Task<T> {
  toPromise(): Promise<T>;
}
/* eslint-disable @typescript-eslint/no-explicit-any */
export interface TaskEngine {
  openDocumentBuffer(file: { id: string; content: ArrayBuffer }, options?: { password?: string; normalizeRotation?: boolean }): Task<any>;
  closeDocument(doc: any): Task<unknown>;
  saveAsCopy(doc: any): Task<ArrayBuffer>;
  setDocumentEncryption(doc: any, user: string, owner: string, flags: number): Task<boolean>;
  setBookmarks(doc: any, bookmarks: any[]): Task<boolean>;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

export interface TaskArgs {
  password?: string | null; // la del PDF que llega, si está cifrado
  user?: string; // encrypt: contraseña para abrirlo
  owner?: string; // encrypt: contraseña de propietario
  permissions?: number; // encrypt: bits de permiso del PDF
  items?: { title: string; page: number }[]; // outline
}

const XYZ = 1; // PdfZoomMode.XYZ

let taskId = 0;

/** Hace `task` sobre el PDF `buffer` y devuelve el PDF resultante. */
export async function runTask(engine: TaskEngine, task: string, buffer: ArrayBuffer, args: TaskArgs): Promise<ArrayBuffer> {
  const doc = await engine.openDocumentBuffer(
    { id: `engine-task-${++taskId}`, content: buffer }, { password: args.password ?? undefined, normalizeRotation: true },
  ).toPromise();
  try {
    if (task === 'encrypt') {
      const done = await engine.setDocumentEncryption(doc, args.user!, args.owner!, args.permissions!).toPromise();
      if (!done) throw new Error('El motor no pudo cifrar el documento.');
    } else if (task === 'outline') {
      await engine.setBookmarks(doc, args.items!.map(({ title, page }) => ({
        title,
        target: { type: 'destination', destination: { pageIndex: page, zoom: { mode: XYZ, params: { x: 0, y: 0, zoom: 0 } }, view: [] } },
      }))).toPromise();
    } else {
      throw new Error(`Tarea desconocida: ${task}`);
    }
    return await engine.saveAsCopy(doc).toPromise();
  } finally {
    await engine.closeDocument(doc).toPromise();
  }
}
