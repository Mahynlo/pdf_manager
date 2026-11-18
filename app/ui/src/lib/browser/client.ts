// La ventana en la versión de navegador: arranca el worker de Python, le pasa las llamadas y
// atiende lo que Python le pide (diálogos, el motor de EmbedPDF). Solo lo usa api.ts.
import { runTask } from '$lib/engine-tasks.ts';
import { engine } from '$lib/engine.ts';
import { t } from '$texts';
import {
  droppedPdfs, fileSize, fileUrl, pickFolder, pickPdfs, pickSave, readFiles, writeBack, writeFile, type FileData,
} from './files.ts';
import type { OnnxReply, OnnxRequest } from './onnx-worker.ts';
import {
  BUSY, CONTROL_SLOTS, DATA_LENGTH, INBOX_BYTES, INBOX_LENGTH, INTERRUPTS, JSON_LENGTH, READY, REPLY_BYTES,
  REPLY_MAX_BYTES, type FromWorker, type ToWorker,
} from './protocol.ts';

type Result = { ok: true; value: unknown } | { ok: false; error: { code: string; message: string } };

/** Lo que `SharedArrayBuffer` tiene y los tipos de TypeScript aún no. */
type GrowableBuffer = SharedArrayBuffer & { grow(length: number): void };

const encoder = new TextEncoder();
let control: Int32Array; // sin aislar la página no existe SharedArrayBuffer: se crean en start()
let inbox: Uint8Array;
let replyBuffer: GrowableBuffer;
let worker: Worker;
let onnx: Worker | null = null; // los modelos del OCR: se arranca la primera vez que hacen falta
let ids = 0;
let dirty = false;
const pending = new Map<number, (result: Result) => void>();

const post = (message: ToWorker, transfer: Transferable[] = []) => worker.postMessage(message, transfer);

/** Escribe la respuesta en la memoria compartida y despierta a Python. */
function answer(value: unknown, parts: Uint8Array[] = []): void {
  const json = encoder.encode(JSON.stringify(value ?? null));
  const dataLength = parts.reduce((total, part) => total + part.length, 0);
  const needed = json.length + dataLength;
  if (needed > replyBuffer.byteLength) replyBuffer.grow(needed);
  const target = new Uint8Array(replyBuffer);
  target.set(json);
  let offset = json.length;
  for (const part of parts) {
    target.set(part, offset);
    offset += part.length;
  }
  Atomics.store(control, JSON_LENGTH, json.length);
  Atomics.store(control, DATA_LENGTH, dataLength);
  Atomics.store(control, READY, 1);
  Atomics.notify(control, READY);
}

/** Respuesta con el contenido de unos archivos: la lista y su contenido, uno detrás de otro. */
function answerFiles(files: FileData[]): void {
  answer({ files: files.map(({ path, data }) => ({ path, size: data.length })) }, files.map(({ data }) => data));
}

/** Pasa una petición al worker de los modelos y escribe su respuesta. */
function runModel(request: Omit<OnnxRequest, 'id' | 'base' | 'data'>, data: Uint8Array | null): void {
  onnx ??= new Worker(new URL('./onnx-worker.ts', import.meta.url), { type: 'module' });
  onnx.onmessage = ({ data: reply }: MessageEvent<OnnxReply>) => {
    if (reply.error) answer({ error: reply.error });
    else answer({ shape: reply.shape ?? null }, reply.data ? [new Uint8Array(reply.data)] : []);
  };
  const base = new URL(import.meta.env.BASE_URL, location.href).href;
  const buffer = data?.buffer as ArrayBuffer | undefined;
  onnx.postMessage({ ...request, id: ++ids, base, data: buffer } satisfies OnnxRequest, buffer ? [buffer] : []);
}

/** Atiende una petición de Python, que espera bloqueado: tiene que responder siempre. */
async function serve(kind: string, json: string, data: Uint8Array | null): Promise<void> {
  const request = JSON.parse(json);
  try {
    if (kind === 'pick') {
      answer(await pickPdfs(request.multiple));
    } else if (kind === 'folder') {
      answer(await pickFolder(request.output));
    } else if (kind === 'read') {
      answerFiles(await readFiles(request.paths));
    } else if (kind === 'size') {
      answer(await fileSize(request.path));
    } else if (kind === 'url') {
      answer(await fileUrl(request.path));
    } else if (kind === 'save') {
      answer(await pickSave(request.name, request.kind));
    } else if (kind === 'engine') {
      const source = data!.buffer as ArrayBuffer;
      answer(null, [new Uint8Array(await runTask(await engine(), request.task, source, request.args))]);
    } else if (kind === 'onnx') {
      runModel(request, data);
    } else {
      throw new Error(`Petición desconocida: ${kind}`);
    }
  } catch (err) {
    console.error(err);
    const message = (err as Error).message ?? String(err);
    answer(kind === 'pick' ? [] : kind === 'read' ? { files: [] } : kind === 'engine' || kind === 'onnx' ? { error: message } : null);
  }
}

function receive(message: FromWorker): void {
  switch (message.type) {
    case 'result':
      pending.get(message.id)?.(JSON.parse(message.json));
      pending.delete(message.id);
      break;
    case 'emit': {
      const payload = JSON.parse(message.json);
      if (message.event === 'browser:open-url') window.open(payload, '_blank', 'noopener,noreferrer');
      else window.pdfm.emit(message.event, payload);
      break;
    }
    case 'ask':
      void serve(message.kind, message.json, message.data);
      break;
    case 'saved':
      void writeBack(message.path, message.data as Uint8Array<ArrayBuffer>);
      break;
    case 'write':
      void writeFile(message.path, message.data as Uint8Array<ArrayBuffer>);
      break;
    case 'dirty':
      dirty = message.dirty;
      break;
    case 'progress':
      window.pdfm.emit('boot:progress', message.step);
      break;
    case 'failed':
      console.error('Fallo en el backend:', message.message);
      break;
  }
}

/** Arranca Python; resuelve cuando ya atiende llamadas. */
export function start(): Promise<void> {
  if (!crossOriginIsolated) return Promise.reject(new Error(t.shell.boot.notIsolated));
  control = new Int32Array(new SharedArrayBuffer(CONTROL_SLOTS * 4));
  inbox = new Uint8Array(new SharedArrayBuffer(INBOX_BYTES));
  const options = { maxByteLength: REPLY_MAX_BYTES } as unknown as number;
  const Shared = SharedArrayBuffer as unknown as new (length: number, options: number) => GrowableBuffer;
  replyBuffer = new Shared(REPLY_BYTES, options);
  worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
  window.addEventListener('beforeunload', (ev) => {
    if (dirty) ev.preventDefault();
  });
  return new Promise((resolve, reject) => {
    worker.onerror = (ev) => reject(new Error(ev.message));
    worker.onmessage = ({ data }: MessageEvent<FromWorker>) => {
      if (data.type === 'ready') resolve();
      else if (data.type === 'failed') reject(new Error(data.message)); // tras arrancar no hace nada
      receive(data);
    };
    post({
      type: 'init',
      base: new URL(import.meta.env.BASE_URL, location.href).href,
      control: control.buffer as SharedArrayBuffer,
      reply: replyBuffer,
      inbox: inbox.buffer as SharedArrayBuffer,
    });
  });
}

export function call(method: string, args: unknown[]): Promise<Result> {
  const id = ++ids;
  const result = new Promise<Result>((resolve) => pending.set(id, resolve));
  const text = JSON.stringify(args);
  if (INTERRUPTS.has(method) && Atomics.load(control, BUSY)) {
    const message = encoder.encode(JSON.stringify({ id, method, args }));
    inbox.set(message);
    Atomics.store(control, INBOX_LENGTH, message.length);
    Atomics.notify(control, INBOX_LENGTH);
  } else {
    post({ type: 'call', id, method, args: text });
  }
  return result;
}

/** Sube `body` a `url` (de `viewer.upload_url`). */
export function upload(url: string, body: ArrayBuffer): void {
  post({ type: 'upload', url, data: new Uint8Array(body) });
}

/** PDF soltados en la ventana: se abren en el visor, que los lee de aquí (files.ts). */
export async function openDropped(transfer: DataTransfer): Promise<void> {
  const paths = await droppedPdfs(transfer);
  if (paths.length) post({ type: 'open', paths: JSON.stringify(paths) });
}
