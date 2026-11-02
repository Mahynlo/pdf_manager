// Respuestas del servicio `merge` (app/backend/services/merge.py).

/** Documento fuente (`MergeService._entry_state`). */
export interface MergeEntry {
  id: number;
  name: string;
  path: string;
  total: number; // páginas del documento
  selected: boolean[]; // una por página
  count: number; // páginas elegidas
  range: string; // la selección como rango («1-3, 5»)
  rotation: number;
  accent: string; // color del documento
}

/** Estado de la herramienta: `state` y cada acción que lo cambia. */
export interface MergeState {
  entries: MergeEntry[];
  preview: [number, number][]; // [documento, página] en el orden final
  output: string | null;
  last_result: string | null;
  busy: boolean;
}

/** Acciones de la tarjeta de un documento (EntryCard.svelte). */
export interface EntryActions {
  toggle(id: number, page: number): void;
  selectAll(id: number, value: boolean): void;
  invert(id: number): void;
  setRange(id: number, text: string): void;
  rotate(id: number, delta: number): void;
  move(id: number, delta: number): void;
  remove(id: number): void;
}
