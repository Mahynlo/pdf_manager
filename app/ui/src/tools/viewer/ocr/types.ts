// Respuestas del servicio `ocr` (app/backend/services/ocr.py).
import type { OcrWord } from '$lib/pdf-engine/index.ts';

/** Rectángulo `[x0, y0, x1, y1]` en puntos de la página tal como se ve. */
export type Box = [number, number, number, number];

/** Texto de una página que ya tiene el documento: `page_text`. */
export interface PageText {
  page: number;
  text: string;
  segments: number;
  boxes: Box[];
  kind: string; // tipo de página: «Escaneado», «Digital»…
  ocr: boolean; // la página tiene texto reconocido
}

/** Reconocimiento de una página (`page`) o de un recorte (`area`). */
export interface OcrResult {
  page: number;
  text: string;
  segments: number;
  boxes: Box[];
  elapsed_ms: number;
  words: OcrWord[]; // las reconocidas (recognize.ts las escribe en el documento)
  mode?: string; // solo `page`
  kind?: string; // solo `page`
}
