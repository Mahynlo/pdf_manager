// Propiedades del documento (PropertiesDialog.svelte). Las da el documento tal como está en el
// visor (EmbedPDF: metadatos, versión, cifrado; las páginas, de `info`), así que no hace falta
// pasárselo antes a Python: de él solo viene el tamaño del archivo en disco.
import type { PdfMetadataObject } from '@embedpdf/models';
import { call } from '$lib/api.ts';
import type { DocumentInfo } from '$lib/types.ts';
import { t } from '$texts';
import type { PageCanvas } from '../canvas/canvas.ts';
import { copies, registry } from '../canvas/embed.ts';
import { pageRotation } from './pages.ts';

const T = t.viewer.properties;
const MM_PER_POINT = 25.4 / 72;
const BYTES_PER_MB = 1024 * 1024;

export interface PropertyRow {
  label: string;
  value: string;
}

/** Lo que muestra el diálogo: título (el nombre del archivo) y filas etiqueta/valor. */
export async function documentProperties(canvas: PageCanvas, info: DocumentInfo): Promise<{ title: string; rows: PropertyRow[] }> {
  const doc = canvas.shownDocument();
  const engine = (await registry()).getEngine();
  const [meta, facts, size] = await Promise.all([
    engine.getMetadata(doc).toPromise(),
    copies().then((c) => c.documentFacts(doc)),
    call<number | null>('viewer.file_size', info.id),
  ]);
  const rows: [string, string][] = [
    [T.location, info.path],
    [T.size, size === null ? T.unknown : T.sizeValue((size / BYTES_PER_MB).toFixed(2), size.toLocaleString('es'))],
    [T.pages, T.pagesValue(info.pages.length)],
  ];
  if (info.pages.length) {
    const [width, height] = info.pages[0]; // como se ve
    rows.push(
      [T.firstPage, T.firstPageValue(
        `${(width * MM_PER_POINT).toFixed(1)} × ${(height * MM_PER_POINT).toFixed(1)}`,
        `${(width / 72).toFixed(2)} × ${(height / 72).toFixed(2)}`,
        `${Math.round(width)} × ${Math.round(height)}`,
      )],
      [T.rotation, `${pageRotation(info.keys[0])}°`],
    );
  }
  rows.push(...metadataRows(meta));
  rows.push(
    [T.version, T.versionValue(facts.version || '1.7')],
    [T.security, facts.encrypted ? T.encrypted : T.notEncrypted],
  );
  return { title: info.name, rows: rows.map(([label, value]) => ({ label, value: value || T.missing })) };
}

function metadataRows(meta: PdfMetadataObject): [string, string][] {
  const date = (value: Date | null) => value?.toLocaleString('es') ?? '';
  return [
    [T.title, meta.title ?? ''],
    [T.author, meta.author ?? ''],
    [T.subject, meta.subject ?? ''],
    [T.keywords, meta.keywords ?? ''],
    [T.creator, meta.creator ?? ''],
    [T.producer, meta.producer ?? ''],
    [T.created, date(meta.creationDate)],
    [T.modified, date(meta.modificationDate)],
  ];
}
