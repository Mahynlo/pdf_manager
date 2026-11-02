// Respuestas del servicio `security` (app/backend/services/security.py).
import type { Tone } from '$lib/ui.ts';

/** Archivo elegido: `pick_unprotected`. */
export interface SecurityFile {
  path: string;
  name: string;
}

/** Análisis de un PDF: `pick_protected`, `inspect` y `unlock`. */
export interface SecurityAudit extends SecurityFile {
  protected: boolean;
  encryption: string | null;
  permissions: { label: string; allowed: boolean }[];
  authenticated: boolean; // se leyeron los permisos con la contraseña
}

/** `options`: permisos y niveles rápidos de «Proteger». */
export interface SecurityOptions {
  permissions: { key: string; label: string }[];
  presets: { key: string; label: string; values: Record<string, boolean> }[];
  default_preset?: string;
}

/** Mensaje del pie de cada pestaña. */
export interface Message {
  text: string;
  tone: Tone;
}
