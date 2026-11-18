// Sellos estándar de EmbedPDF (Aprobado, Borrador, Confidencial, Firmar aquí…), en español:
// el paquete @embedpdf/default-stamps (MIT) va dentro de la app. Sin esto el complemento de
// sellos los descargaría de su CDN al arrancar (ver embed.ts).
import { PdfAnnotationName } from '@embedpdf/models';
import type { StampLibraryConfig } from '@embedpdf/plugin-stamp';
import manifest from '@embedpdf/default-stamps/es/manifest.json';
import pdfUrl from '@embedpdf/default-stamps/es/stamps.pdf?url';

export const STANDARD = 'standard';

/** Biblioteca de solo lectura. La URL va absoluta: la abre el motor, que corre en un worker. */
export const STANDARD_LIBRARY: StampLibraryConfig = {
  id: STANDARD,
  name: manifest.name,
  pdf: new URL(pdfUrl, location.href).href,
  // El manifiesto nombra el tipo de sello con texto («Approved»); la biblioteca lo quiere como número.
  stamps: manifest.stamps.map((stamp) => ({
    ...stamp, name: PdfAnnotationName[stamp.name as keyof typeof PdfAnnotationName] ?? PdfAnnotationName.Custom,
  })),
  readonly: true,
};
