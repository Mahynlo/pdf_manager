// Textos de la interfaz: nombres de botones, descripciones emergentes, menús y avisos. Están
// todos en el catálogo del idioma (es.ts), ordenados por herramienta y parte, para cambiarlos
// sin buscar por el código:
//
//   import { t, tip } from '$texts';
//   <button title={tip(t.viewer.toolbar.undo)}>      →  «Deshacer (Ctrl+Z)»
//
// Otro idioma sería otro catálogo con las mismas claves (`const en: Texts = { ... }`): TypeScript
// avisa si falta alguna o sobra.
import es from './es';

export type Texts = typeof es;

/** Texto de un botón, con su atajo de teclado si lo tiene. */
export type Label = string | { label: string; shortcut?: string };

export const t: Texts = es;

/** Texto para el `title` de un botón: «Etiqueta (atajo)». */
export function tip(text: Label): string {
  if (typeof text === 'string') return text;
  return text.shortcut ? `${text.label} (${text.shortcut})` : text.label;
}
