// Mensajes entre la ventana (index.ts) y el worker del motor (worker.ts). Es el protocolo del
// worker de EmbedPDF 2.15.1 (su RemoteExecutor y su runner), para que su PdfEngine funcione igual.

/** Id con el que el worker avisa de que el motor está listo. */
export const READY_ID = '0';

export type ToEngine =
  | { type: 'wasmInit'; wasmUrl: string }
  | { type: 'execute'; id: string; method: string; args: unknown[] };

/** Error de una tarea, como lo da EmbedPDF (`TaskError`). */
export interface EngineError {
  type: 'reject' | 'abort';
  reason: { code: number; message: string };
}

export type FromEngine =
  | { type: 'ready'; id: string }
  | { type: 'wasmError'; error: string }
  | { type: 'result'; id: string; data: unknown }
  | { type: 'progress'; id: string; progress: unknown }
  | { type: 'error'; id: string; error: EngineError };
