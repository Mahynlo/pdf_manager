// Tipos de las respuestas del backend Python (servicios de app/backend/services) que usa más de
// una parte de la interfaz. Los de una sola herramienta van junto a ella.
//
//   const info = await call<DocumentInfo>('viewer.open', path);

/** `app.settings`. */
export interface AppSettings {
  dark_theme: boolean;
}

/** Entrada de `documents.recent` (también `remove_recent` y `clear_recent`). */
export interface RecentFile {
  path: string;
  name: string;
  folder: string;
}

/** Entrada del índice de un PDF. */
export interface TocEntry {
  level: number;
  title: string;
  page: number; // desde 0
}

/** Documento abierto en el visor: `viewer.open` y las operaciones que lo cambian (`ViewerService._info`). */
export interface DocumentInfo {
  id: number;
  path: string;
  name: string;
  pages: [number, number][]; // [ancho, alto] de cada página, en puntos
  keys: string[]; // identifica la imagen de cada página: cambia al girarla o editarla
  toc: TocEntry[];
  modified: boolean;
  redacted: boolean; // con censura aplicada: solo se guarda como copia
  page_undo: boolean; // hay operaciones de página que deshacer
  page_redo: boolean;
}
