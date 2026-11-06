// El backend de Python en el navegador: arranca Pyodide y le pasa las llamadas de la ventana.
// Va en un worker para que Python no bloquee la interfaz. Ver docs/web/navegador.md.
import type { PyodideAPI } from 'pyodide';
import {
  BUSY, DATA_LENGTH, INBOX_LENGTH, JSON_LENGTH, READY, type FromWorker, type Init, type ToWorker,
} from './protocol.ts';

const HOME = '/home/pyodide'; // preferencias, leyendas, sellos y firmas: se conservan en IndexedDB
const BACKEND_ROOT = '/backend';
const PERSIST_DELAY_MS = 1000;
const BLOB_LIFETIME_MS = 120_000;

/** Lo que Python usa de `Backend` (app/browser/main.py). */
interface Backend {
  call(method: string, args: string): string;
  settle(): void;
  add_file(path: string, data: Uint8Array): void;
  open_files(paths: string): void;
  upload(url: string, data: Uint8Array): void;
}

const scope = self as unknown as {
  postMessage(message: FromWorker, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<ToWorker>) => void) | null;
};

const decoder = new TextDecoder();
let py: PyodideAPI;
let backend: Backend;
let control: Int32Array;
let reply: Uint8Array; // sigue el tamaño del búfer al crecer
let inbox: Uint8Array;
let persisting: ReturnType<typeof setTimeout> | undefined;

/** Lo que llama Python (app.browser.main.JsChannel). */
const channel = {
  ask(kind: string, json: string, data: Uint8Array | null) {
    const copy = data?.slice() ?? null;
    Atomics.store(control, READY, 0);
    scope.postMessage({ type: 'ask', kind, json, data: copy }, copy ? [copy.buffer] : []);
    Atomics.wait(control, READY, 0);
    const jsonLength = Atomics.load(control, JSON_LENGTH);
    const dataLength = Atomics.load(control, DATA_LENGTH);
    return {
      json: decoder.decode(reply.slice(0, jsonLength)),
      data: reply.slice(jsonLength, jsonLength + dataLength),
    };
  },
  emit(event: string, json: string) {
    scope.postMessage({ type: 'emit', event, json });
  },
  share(data: Uint8Array, type: string) {
    const url = URL.createObjectURL(new Blob([data.slice()], { type }));
    setTimeout(() => URL.revokeObjectURL(url), BLOB_LIFETIME_MS);
    return url;
  },
  saved(path: string, data: Uint8Array) {
    const copy = data.slice();
    scope.postMessage({ type: 'saved', path, data: copy }, [copy.buffer]);
  },
  /** Una llamada que interrumpe el trabajo en curso, si llega en `ms` (ver INTERRUPTS). */
  poll(ms: number) {
    if (!Atomics.load(control, INBOX_LENGTH) && ms > 0) Atomics.wait(control, INBOX_LENGTH, 0, ms);
    const length = Atomics.load(control, INBOX_LENGTH);
    if (!length) return ''; // un null llegaría a Python como JsNull, no como None
    const text = decoder.decode(inbox.slice(0, length));
    Atomics.store(control, INBOX_LENGTH, 0);
    return text;
  },
  reply(id: number, json: string) {
    scope.postMessage({ type: 'result', id, json });
  },
  busy(on: boolean) {
    Atomics.store(control, BUSY, on ? 1 : 0);
  },
  dirty(dirty: boolean) {
    scope.postMessage({ type: 'dirty', dirty });
  },
};

const syncHome = (load: boolean) => new Promise<void>((resolve, reject) => {
  py.FS.syncfs(load, (err: unknown) => (err ? reject(err) : resolve()));
});

function persistSoon(): void {
  clearTimeout(persisting);
  persisting = setTimeout(() => void syncHome(false).catch(console.error), PERSIST_DELAY_MS);
}

async function start({ base, control: sharedControl, reply: sharedReply, inbox: sharedInbox }: Init): Promise<void> {
  control = new Int32Array(sharedControl);
  reply = new Uint8Array(sharedReply);
  inbox = new Uint8Array(sharedInbox);
  const indexURL = `${base}pyodide/`;
  const { loadPyodide } = await import(/* @vite-ignore */ `${indexURL}pyodide.mjs`) as typeof import('pyodide');
  py = await loadPyodide({ indexURL });
  scope.postMessage({ type: 'progress', step: 1 });
  const [manifest, archive] = await Promise.all([
    fetch(`${base}backend.json`).then((r) => r.json()) as Promise<{ packages: string[]; wheels: string[] }>,
    fetch(`${base}backend.zip`).then((r) => r.arrayBuffer()),
  ]);
  await py.loadPackage([...manifest.packages, ...manifest.wheels.map((name) => indexURL + name)], { messageCallback: () => {} });
  py.unpackArchive(archive, 'zip', { extractDir: BACKEND_ROOT });
  py.FS.mount((py.FS as unknown as { filesystems: { IDBFS: never } }).filesystems.IDBFS, {}, HOME);
  await syncHome(true).catch(console.error); // sin lo guardado también se puede trabajar
  scope.postMessage({ type: 'progress', step: 2 });
  py.runPython(`import sys; sys.path.insert(0, ${JSON.stringify(BACKEND_ROOT)})`);
  backend = py.pyimport('app.browser.main').Backend(channel);
  scope.postMessage({ type: 'ready' });
}

function settle(): void {
  try {
    backend.settle();
  } catch (err) {
    scope.postMessage({ type: 'failed', message: (err as Error).message ?? String(err) });
  }
  persistSoon();
}

scope.onmessage = ({ data: message }) => {
  switch (message.type) {
    case 'init':
      start(message).catch((err: Error) => {
        console.error(err);
        scope.postMessage({ type: 'failed', message: err.message ?? JSON.stringify(err) });
      });
      break;
    case 'call':
      scope.postMessage({ type: 'result', id: message.id, json: backend.call(message.method, message.args) });
      settle();
      break;
    case 'file':
      backend.add_file(message.path, message.data);
      break;
    case 'open':
      backend.open_files(message.paths);
      settle();
      break;
    case 'upload':
      backend.upload(message.url, message.data);
      break;
  }
};
