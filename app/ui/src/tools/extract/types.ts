// Respuestas y eventos del servicio `extract` (app/backend/services/extract).

/** Estado de la herramienta: `state` y las acciones que lo cambian. */
export interface ExtractJob {
  reference: { name: string; path: string; kind: string } | null;
  targets: { path: string; name: string }[];
  destination: { path: string; name: string };
  running: boolean;
  last_output: string | null;
}

/** Coincidencia de la tabla (evento `extract:match`). */
export interface ExtractMatch {
  name: string;
  page: number; // desde 1
  score: number;
  terms: string;
  mode: string;
}

/** Tono de una línea del registro (`extract:log`). */
export type LogTone = 'success' | 'warning' | 'danger' | 'muted' | 'info' | null | undefined;
