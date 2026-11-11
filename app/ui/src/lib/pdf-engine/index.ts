// El motor PDFium de la app: el PdfEngine de EmbedPDF sobre nuestro worker (worker.ts), que
// añade lo que le falta para cambiar las páginas de un documento abierto, sacar copias de él y
// leer y escribir lo que necesita el OCR (native.ts).
//
// Sustituye a createPdfiumEngine de EmbedPDF, que crea su worker desde un blob y no deja
// añadirle métodos. Este hace lo mismo: el worker, el ejecutor que le pasa las llamadas por su
// nombre y el codificador de imágenes en workers.
import { PdfEngine, createHybridImageConverter } from '@embedpdf/engines';
import { Task, type IPdfiumExecutor, type PdfDocumentObject, type PdfPageObject } from '@embedpdf/models';
import { ImageEncoderPool } from './encoder.ts';
import type { CopyMethod, CopyOptions, DocumentFacts, ReadingMethod, StructureMethod } from './native.ts';
import type { OcrText, PageFacts, PageImage } from './page-ocr.ts';
import type { Box } from './page-reader.ts';
import type { PageTexts } from './page-text.ts';
import { READY_ID, type FromEngine, type ToEngine } from './protocol.ts';

const ENCODERS = 2; // workers que codifican imágenes (los mismos que EmbedPDF)
const INIT_FAILED = 1; // PdfErrorCode.Initialization

/** Pasa cada llamada al worker y devuelve su resultado como una tarea de EmbedPDF. */
class WorkerExecutor {
  private worker: Worker;
  private ids = 0;
  private tasks = new Map<string, Task<unknown, unknown, unknown>>();
  private ready: Promise<void>;

  constructor(wasmUrl: string) {
    this.worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = ({ data }: MessageEvent<FromEngine>) => {
        if (data.type === 'ready' && data.id === READY_ID) resolve();
        else if (data.type === 'wasmError') reject(new Error(data.error));
        else this.settle(data);
      };
    });
    this.post({ type: 'wasmInit', wasmUrl });
  }

  private post(message: ToEngine): void {
    this.worker.postMessage(message);
  }

  send<R>(method: string, args: unknown[]): Task<R, unknown, unknown> {
    const id = `req-${++this.ids}`;
    const task = new Task<R, unknown, unknown>();
    this.ready.then(
      () => {
        this.tasks.set(id, task as Task<unknown, unknown, unknown>);
        this.post({ type: 'execute', id, method, args });
      },
      () => task.reject({ code: INIT_FAILED, message: 'No se pudo iniciar el motor PDF' }),
    );
    return task;
  }

  private settle(message: FromEngine): void {
    if (!('id' in message)) return;
    const task = this.tasks.get(message.id);
    if (!task) return;
    if (message.type === 'progress') {
      task.progress(message.progress);
      return;
    }
    this.tasks.delete(message.id);
    if (message.type === 'result') task.resolve(message.data);
    else if (message.type === 'error') task.fail(message.error);
  }

  destroy(): void {
    for (const task of this.tasks.values()) task.abort('Motor cerrado');
    this.tasks.clear();
    this.worker.terminate();
  }
}

/** Las operaciones que añade el motor de la app (native.ts), con sus tipos. */
export class PageStructure {
  constructor(private executor: WorkerExecutor) {}

  private call<R>(method: StructureMethod, ...args: unknown[]): Promise<R> {
    return this.executor.send<R>(method, args).toPromise();
  }

  pageList(doc: PdfDocumentObject): Promise<PdfPageObject[]> {
    return this.call('pageList', doc);
  }

  rotatePages(doc: PdfDocumentObject, indices: number[], turns: number): Promise<PdfPageObject[]> {
    return this.call('rotatePages', doc, indices, turns);
  }

  movePage(doc: PdfDocumentObject, from: number, to: number): Promise<PdfPageObject[]> {
    return this.call('movePage', doc, from, to);
  }

  removePage(doc: PdfDocumentObject, index: number): Promise<PdfPageObject[]> {
    return this.call('removePage', doc, index);
  }

  insertBlankPage(doc: PdfDocumentObject, index: number, width: number, height: number): Promise<PdfPageObject[]> {
    return this.call('insertBlankPage', doc, index, width, height);
  }

  duplicatePage(doc: PdfDocumentObject, index: number, at: number): Promise<PdfPageObject[]> {
    return this.call('duplicatePage', doc, index, at);
  }

  stashPage(doc: PdfDocumentObject, index: number): Promise<string> {
    return this.call('stashPage', doc, index);
  }

  restorePages(doc: PdfDocumentObject, stash: string, at: number): Promise<PdfPageObject[]> {
    return this.call('restorePages', doc, stash, at);
  }

  dropStash(stash: string): Promise<boolean> {
    return this.call('dropStash', stash);
  }
}

/** Copias del documento abierto que salen del visor: a disco, a Python o a la impresora (native.ts). */
export class DocumentCopies {
  constructor(private executor: WorkerExecutor) {}

  private call<R>(method: CopyMethod, ...args: unknown[]): Promise<R> {
    return this.executor.send<R>(method, args).toPromise();
  }

  saveCopy(doc: PdfDocumentObject, options: CopyOptions): Promise<ArrayBuffer> {
    return this.call('saveCopy', doc, options);
  }

  extractCopy(doc: PdfDocumentObject, indices: number[], withoutText: number[]): Promise<ArrayBuffer> {
    return this.call('extractCopy', doc, indices, withoutText);
  }

  documentFacts(doc: PdfDocumentObject): Promise<DocumentFacts> {
    return this.call('documentFacts', doc);
  }
}

/** Leer el documento abierto: lo que necesita el OCR (page-ocr.ts) y el texto de las páginas para Python (page-text.ts). */
export class PageReading {
  constructor(private executor: WorkerExecutor) {}

  private call<R>(method: ReadingMethod, ...args: unknown[]): Promise<R> {
    return this.executor.send<R>(method, args).toPromise();
  }

  pageFacts(doc: PdfDocumentObject, index: number): Promise<PageFacts> {
    return this.call('pageFacts', doc, index);
  }

  pageImage(doc: PdfDocumentObject, index: number, scale: number, clip?: Box): Promise<PageImage> {
    return this.call('pageImage', doc, index, scale, clip);
  }

  /** Devuelve las páginas que cambiaron (las que hay que volver a leer en EmbedPDF). */
  writeOcrText(doc: PdfDocumentObject, pages: OcrText[]): Promise<number[]> {
    return this.call('writeOcrText', doc, pages);
  }

  pageTexts(doc: PdfDocumentObject, indices: number[]): Promise<PageTexts> {
    return this.call('pageTexts', doc, indices);
  }
}

export interface AppEngine {
  engine: PdfEngine<Blob>; // el que usan EmbedPDF y las tareas de Python (engine-tasks.ts)
  structure: PageStructure;
  copies: DocumentCopies;
  reading: PageReading;
}

/** Arranca el motor con el wasm de `wasmUrl` (URL absoluta). */
export function createAppEngine(wasmUrl: string): AppEngine {
  const executor = new WorkerExecutor(wasmUrl);
  // PdfEngine llama al ejecutor por cada método de PDFium: todos van al worker por su nombre.
  const remote = new Proxy(executor, {
    get: (target, name, receiver) =>
      name in target ? Reflect.get(target, name, receiver) : (...args: unknown[]) => target.send(String(name), args),
  }) as unknown as IPdfiumExecutor;
  const engine = new PdfEngine<Blob>(remote, { imageConverter: createHybridImageConverter(new ImageEncoderPool(ENCODERS) as never) });
  return {
    engine,
    structure: new PageStructure(executor),
    copies: new DocumentCopies(executor),
    reading: new PageReading(executor),
  };
}

export type { OcrText, OcrWord, PageFacts, PageImage } from './page-ocr.ts';
export type { Box } from './page-reader.ts';
export type { PageTexts } from './page-text.ts';
