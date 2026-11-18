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

/** El estado de un documento abierto que da Python (`ViewerService._info`: guardar, censurar…). */
export interface DocumentState {
  id: number;
  path: string;
  name: string;
  modified: boolean; // cambios sin guardar (en el visor lo calcula operations.ts)
  annotated: boolean; // anotaciones cambiadas sin guardar
  redacted: boolean; // con censura aplicada: solo se guarda como copia
}

/**
 * Documento abierto en el visor. Al abrirlo lo da Python (`viewer.open`: el archivo); después,
 * las páginas las lleva el visor y Python solo da el estado (`DocumentState`).
 */
export interface DocumentInfo extends DocumentState {
  pages: [number, number][]; // [ancho, alto] de cada página, en puntos
  keys: string[]; // identifica la imagen de cada página: cambia al girarla o editarla
  toc: TocEntry[];
}
