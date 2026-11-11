// El OCR del visor sin que Python lea el documento: el motor de la app (lib/pdf-engine) dice qué
// tiene la página y dibuja lo que hay que reconocer, Python lo reconoce (servicio `ocr`) y el
// motor escribe las palabras en el documento a la vista como texto invisible, que EmbedPDF
// selecciona y busca como el nativo (sin volver a abrir el documento).
//
// También la orientación de una página: la dice el sentido de su texto o, en un escaneo, Python
// mirando dos imágenes de ella.
//
// Las resoluciones son las de pdf_core/ocr/processor.py, que hace lo mismo con los archivos
// (herramienta Extraer): cambiarlas en los dos sitios.
import { call } from '$lib/api.ts';
import type { Box, OcrWord, PageFacts, PageImage } from '$lib/pdf-engine/index.ts';
import type { PageCanvas } from '../canvas/canvas.ts';
import { reading } from '../canvas/embed.ts';
import { send } from '../document/copy.ts';
import type { OcrResult } from './types.ts';

const PAGE_SCALE = 2; // px por punto para reconocer una página (_SCALE_FOR_OCR)
const PAGE_MAX_PX = 2000; // lado mayor de cada imagen (_MAX_OCR_PX)
const MIN_IMAGE = 8; // pt: una imagen más pequeña no se reconoce
const AREA_SCALE = { min: 1.5, max: 2.5, px: 1600 }; // recortes: más resolución (prepare_area)
const SMALL_SCALE = 0.8; // imagen con la que Python clasifica la orientación (_SMALL_SCALE)
const PROBE = { max: 1.5, px: 1400 }; // sonda de la orientación (render_orientation_probe)
const TEXT_DECIDES = 30; // con estos caracteres, la orientación la dice el texto

/** Una imagen que reconoce Python: `rect` de la página vista dibujado a `scale` px por punto. */
interface Region {
  rect: Box;
  scale: number;
  width: number;
  height: number;
}

export class PageRecognizer {
  constructor(private canvas: PageCanvas, private docId: number) {}

  /**
   * OCR de la página `index`: sus imágenes o, si no tiene, la página entera. Su texto
   * reconocido sustituye al que tenía. Python tiene que tener el documento al día.
   */
  async page(index: number): Promise<OcrResult> {
    const key = this.canvas.keys[index];
    const facts = await this.facts(index);
    const plan = imageRects(facts, this.canvas.sizes[index]).map((rect) => ({ rect, scale: pageScale(rect) }));
    const { url, regions } = await this.upload(index, plan);
    const result = await call<OcrResult>('ocr.page', this.docId, index, url, regions,
      { lines: facts.lines, images: facts.images.length > 0 });
    await this.write(index, key, result.words, true);
    return result;
  }

  /** OCR del rectángulo `rect` (puntos de la página vista): sus palabras se suman a las de la página. */
  async area(index: number, rect: Box): Promise<OcrResult> {
    const key = this.canvas.keys[index];
    const longest = Math.max(rect[2] - rect[0], rect[3] - rect[1]);
    const scale = Math.min(AREA_SCALE.max, Math.max(AREA_SCALE.min, AREA_SCALE.px / longest));
    const { url, regions } = await this.upload(index, [{ rect, scale }]);
    const result = await call<OcrResult>('ocr.area', this.docId, index, url, regions[0]);
    await this.write(index, key, result.words, false);
    return result;
  }

  /** Los grados que hay que girar la página `index` para dejarla derecha (0: está bien). */
  async orientation(index: number): Promise<number> {
    const byText = textCorrection(await this.facts(index));
    if (byText !== null) return byText;
    const [width, height] = this.canvas.sizes[index];
    const probe = Math.min(PROBE.max, PROBE.px / Math.max(1, width, height));
    const images = await this.draw(index, [{ scale: SMALL_SCALE }, { scale: probe }]);
    const url = await send(joined(images));
    const { angle } = await call<{ angle: number }>('ocr.orientation', url, images.map(({ width, height }) => ({ width, height })));
    return angle;
  }

  // ── Auxiliares ─────────────────────────────────────────────────────────
  private async facts(index: number): Promise<PageFacts> {
    return (await reading()).pageFacts(this.canvas.shownDocument(), index);
  }

  /** Dibuja con el motor cada trozo de la página (`rect`; sin él, la página entera). */
  private async draw(index: number, parts: { rect?: Box; scale: number }[]): Promise<PageImage[]> {
    const engine = await reading();
    const doc = this.canvas.shownDocument();
    const images: PageImage[] = [];
    for (const { rect, scale } of parts) images.push(await engine.pageImage(doc, index, scale, rect));
    return images;
  }

  /** Dibuja las regiones y las sube a Python, todas juntas. */
  private async upload(index: number, plan: { rect: Box; scale: number }[]): Promise<{ url: string; regions: Region[] }> {
    const images = await this.draw(index, plan);
    const url = await send(joined(images));
    return { url, regions: plan.map((part, i) => ({ ...part, width: images[i].width, height: images[i].height })) };
  }

  /** Escribe las palabras en el documento a la vista, si la página sigue siendo la misma. */
  private async write(index: number, key: string, words: OcrWord[], replace: boolean): Promise<void> {
    if (this.canvas.keys[index] !== key) return; // cambió mientras se reconocía: las tiene Python
    await this.canvas.writeOcrText([{ index, words, replace }]);
  }
}

/** Dónde reconocer: las imágenes de la página (recortadas a ella) o, si no tiene, la página entera. */
function imageRects({ images }: PageFacts, [width, height]: [number, number]): Box[] {
  const rects = images
    .map(([x0, y0, x1, y1]): Box => [Math.max(0, x0), Math.max(0, y0), Math.min(width, x1), Math.min(height, y1)])
    .filter(([x0, y0, x1, y1]) => x1 - x0 >= MIN_IMAGE && y1 - y0 >= MIN_IMAGE);
  return rects.length ? rects : [[0, 0, width, height]];
}

function pageScale([x0, y0, x1, y1]: Box): number {
  const longest = Math.max(x1 - x0, y1 - y0);
  return Math.max(1, longest * PAGE_SCALE > PAGE_MAX_PX ? PAGE_MAX_PX / longest : PAGE_SCALE);
}

/**
 * La orientación que dice el texto de la página (como detect_orientation_native en Python), o
 * null si no tiene texto suficiente para decidirlo (un escaneo).
 */
function textCorrection({ chars, direction: [wx, wy] }: PageFacts): number | null {
  let angle = 0;
  if (wx || wy) angle = Math.abs(wx) >= Math.abs(wy) ? (wx >= 0 ? 0 : 180) : wy < 0 ? 90 : 270;
  return angle || chars >= TEXT_DECIDES ? angle : null;
}

/** Las imágenes una tras otra, como las lee Python. */
function joined(images: PageImage[]): ArrayBuffer {
  const out = new Uint8Array(images.reduce((total, image) => total + image.data.byteLength, 0));
  let offset = 0;
  for (const image of images) {
    out.set(new Uint8Array(image.data), offset);
    offset += image.data.byteLength;
  }
  return out.buffer;
}
