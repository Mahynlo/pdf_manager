// Lo que comparten la ventana (client.ts) y el worker de Python (worker.ts).
//
// Python es síncrono: cuando necesita a la ventana (un diálogo, el motor de EmbedPDF) la llama y
// espera, y mientras tanto el worker no recibe mensajes. Por eso las respuestas no vuelven con
// postMessage: la ventana las escribe en memoria compartida y despierta al worker (Atomics). La
// memoria compartida exige que la página esté aislada (cabeceras COOP y COEP).

/** Posiciones de `control` (Int32Array). */
export const READY = 0; // 1 cuando hay una respuesta en `reply`
export const JSON_LENGTH = 1; // bytes del JSON de la respuesta, al principio de `reply`
export const DATA_LENGTH = 2; // bytes de datos, detrás del JSON
export const BUSY = 3; // 1 mientras el worker hace un trabajo largo
export const INBOX_LENGTH = 4; // bytes de la llamada que espera en `inbox`
export const CONTROL_SLOTS = 8;

export const INBOX_BYTES = 64 * 1024;
export const REPLY_BYTES = 1024 * 1024;
export const REPLY_MAX_BYTES = 2 ** 31; // se reserva, no se ocupa: crece con cada respuesta

/** Llamadas que tienen que llegar aunque el worker esté en un trabajo largo. */
export const INTERRUPTS: ReadonlySet<string> = new Set(['extract.cancel', 'extract.answer_password']);

export interface Init {
  type: 'init';
  base: string; // URL de la raíz de la web
  control: SharedArrayBuffer;
  reply: SharedArrayBuffer;
  inbox: SharedArrayBuffer;
}

/** De la ventana al worker. */
export type ToWorker =
  | Init
  | { type: 'call'; id: number; method: string; args: string }
  | { type: 'open'; paths: string }
  | { type: 'upload'; url: string; data: Uint8Array };

/** Del worker a la ventana. */
export type FromWorker =
  | { type: 'ready' }
  | { type: 'progress'; step: number } // paso del arranque (textos: shell.boot.steps)
  | { type: 'failed'; message: string }
  | { type: 'result'; id: number; json: string }
  | { type: 'emit'; event: string; json: string }
  | { type: 'ask'; kind: string; json: string; data: Uint8Array | null }
  | { type: 'saved'; path: string; data: Uint8Array } // Python tiene copia (files.ts: writeBack)
  | { type: 'write'; path: string; data: Uint8Array } // Python no tiene copia (files.ts: writeFile)
  | { type: 'dirty'; dirty: boolean };
