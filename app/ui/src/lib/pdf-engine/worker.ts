// Worker del motor PDFium: el de EmbedPDF, pero con AppNative (native.ts). Atiende las llamadas
// de la ventana (index.ts) por el nombre del método, como el runner de EmbedPDF 2.15.1.
import { init } from '@embedpdf/pdfium';
import { AppNative } from './native.ts';
import { READY_ID, type EngineError, type FromEngine, type ToEngine } from './protocol.ts';

const UNKNOWN = 0; // PdfErrorCode.Unknown

const scope = self as unknown as {
  postMessage(message: FromEngine, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<ToEngine>) => void) | null;
};

let native: AppNative | null = null;

/** Lo que devuelven los métodos de PdfiumNative que no son inmediatos (un `PdfTask`). */
interface TaskLike {
  wait(done: (data: unknown) => void, failed: (error: EngineError) => void): void;
  onProgress(cb: (progress: unknown) => void): void;
}

const isTask = (value: unknown): value is TaskLike => typeof value === 'object' && value !== null && 'wait' in value;

/** Entrega el resultado: un PDF (ArrayBuffer) pasa a la ventana sin copiarlo. */
const reply = (id: string, data: unknown): void =>
  scope.postMessage({ type: 'result', id, data }, data instanceof ArrayBuffer ? [data] : []);

const failure = (id: string, err: unknown): FromEngine => ({
  type: 'error', id, error: { type: 'reject', reason: { code: UNKNOWN, message: (err as Error)?.message ?? String(err) } },
});

async function start(wasmUrl: string): Promise<void> {
  try {
    const wasmBinary = await (await fetch(wasmUrl)).arrayBuffer();
    native = new AppNative(await init({ wasmBinary }));
    scope.postMessage({ type: 'ready', id: READY_ID });
  } catch (err) {
    scope.postMessage({ type: 'wasmError', error: (err as Error)?.message ?? String(err) });
  }
}

function execute(id: string, method: string, args: unknown[]): void {
  const target = native as unknown as Record<string, ((...a: unknown[]) => unknown) | undefined> | null;
  const fn = target?.[method];
  if (typeof fn !== 'function') {
    scope.postMessage(failure(id, new Error(`Método no disponible: ${method}`)));
    return;
  }
  try {
    const result = fn.apply(native, args);
    if (!isTask(result)) {
      reply(id, result);
      return;
    }
    result.onProgress((progress) => scope.postMessage({ type: 'progress', id, progress }));
    result.wait(
      (data) => reply(id, data),
      (error) => scope.postMessage({ type: 'error', id, error }),
    );
  } catch (err) {
    scope.postMessage(failure(id, err));
  }
}

scope.onmessage = ({ data: message }) => {
  if (message.type === 'wasmInit') {
    if (!native) void start(message.wasmUrl);
  } else {
    execute(message.id, message.method, message.args);
  }
};
