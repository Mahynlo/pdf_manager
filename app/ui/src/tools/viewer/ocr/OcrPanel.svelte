<!--
  Pestaña «OCR» del panel lateral (ocr_panel.py y ocr_worker.py en Qt): OCR de la
  página actual, de un recorte y por lotes, cajas del texto reconocido en el lienzo y
  texto extraído. Reconoce `recognizer` (recognize.ts: el motor dibuja, Python reconoce);
  las palabras quedan escritas en el documento, así se pueden seleccionar y buscar, y en
  Python, en la capa de texto de la página.
-->
<script lang="ts">
  import { call, type ApiError } from '$lib/api.ts';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Icon from '$lib/Icon.svelte';
  import { openModal, setStatus, toast } from '$lib/ui.ts';
  import { t } from '$texts';
  import { TOOLS, type PageCanvas } from '../canvas/canvas.ts';
  import OcrBatchDialog from './OcrBatchDialog.svelte';
  import OcrResultDialog from './OcrResultDialog.svelte';
  import type { PageRecognizer } from './recognize.ts';
  import type { Box, OcrResult } from './types.ts';

  const T = t.viewer.ocr;
  const MIN_AREA = 4; // pt: un recorte más pequeño es un clic, no un rectángulo

  /**
   * `page`: página actual; `active`: la pestaña está a la vista (solo entonces se pide el
   * texto de cada página); `changed(index)`: el texto de la página cambió (la búsqueda lo
   * relee); `orient()`: corregir la orientación de la página actual.
   */
  let { canvas, docId, recognizer, page, active, close, setTool, changed, orient, syncText }: {
    canvas: PageCanvas;
    docId: number;
    recognizer: PageRecognizer;
    /** Python recibe las páginas al día y el texto de `pages` (sin ellas, de todas) antes de leerlo. */
    syncText: (pages?: number[] | null) => Promise<unknown>;
    page: number;
    active: boolean;
    close: () => void;
    setTool: (tool: string) => void;
    changed: (index: number) => void;
    orient: () => void;
  } = $props();

  let mode = $state(T.mode);
  let kind = $state('-');
  let time = $state('-');
  let segments = $state('-');
  let text = $state('');
  let busy = $state(false);
  let showBoxes = $state(false); // apagado por defecto, como en Qt: cubría cada página de cajas verdes
  let boxes = $state.raw(new Map<number, Box[]>()); // página -> cajas del último resultado
  let run = 0; // descarta respuestas de páginas anteriores

  const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

  /** Tras cambiar las páginas (girar, mover…): las cajas se perdieron y el texto puede ser otro. */
  export function refresh() {
    boxes = new Map();
    if (active) load();
  }

  $effect(() => {
    if (active) load(page);
  });

  // Cajas del texto reconocido sobre la página actual.
  $effect(() => {
    const rects = active && showBoxes ? (boxes.get(page) ?? []) : [];
    const marks: HTMLElement[] = rects.map((rect) => canvas.addMark(page, rect, 'ocr-box'));
    return () => marks.forEach((mark) => mark.remove());
  });

  function setBoxes(index: number, rects: Box[]) {
    boxes = new Map(boxes).set(index, rects);
  }

  async function load(index = page) {
    const mine = ++run;
    try {
      await syncText([index]);
      const result = await recognizer.pageText(index);
      if (mine !== run) return;
      kind = result.kind;
      segments = String(result.segments);
      text = result.text || T.noText;
      setBoxes(index, result.boxes);
    } catch (err) {
      if (mine === run && (err as ApiError).code !== 'bad_page') toast((err as Error).message, 'danger');
    }
  }

  /** Muestra un resultado de `ocr.page` u `ocr.area` y avisa de que cambió el texto de la página. */
  function showResult(result: OcrResult, label: string) {
    run++; // una carga de texto pendiente ya no vale
    time = seconds(result.elapsed_ms);
    segments = String(result.segments);
    mode = label;
    setBoxes(result.page, result.boxes);
    changed(result.page);
  }

  async function withBusy(label: string, fn: () => Promise<void>) {
    if (busy) return;
    busy = true;
    const previous = mode;
    mode = label;
    try {
      await fn();
    } catch (err) {
      const { code, message } = err as ApiError;
      mode = previous;
      if (code !== 'stale') text = message;
      toast(message, 'danger');
    } finally {
      busy = false;
    }
  }

  function runPage() {
    const index = page;
    withBusy(T.processing, async () => {
      await syncText([index]);
      const result = await recognizer.page(index);
      showResult(result, T.modeOf(result.mode ?? ''));
      kind = result.kind ?? '-';
      if (index === page) text = result.text || T.noTextFound;
    });
  }

  function copy() {
    const value = text.trim();
    if (!value || value === T.noText) return;
    navigator.clipboard.writeText(value)
      .then(() => setStatus(T.copied))
      .catch((err: Error) => toast(T.copyError(err.message), 'danger'));
  }

  // ── Recorte ────────────────────────────────────────────────────────────
  function startArea() {
    setTool(TOOLS.AREA_OCR);
    setStatus(T.areaHint);
  }

  const clamp = (index: number, [x, y]: number[]): [number, number] => {
    const [w, ht] = canvas.sizes[index];
    return [Math.min(w, Math.max(0, x)), Math.min(ht, Math.max(0, y))];
  };

  const rectOf = ({ start, end }: { start: [number, number]; end: [number, number] }): Box => {
    const r = (v: number) => Math.round(v * 100) / 100;
    return [r(Math.min(start[0], end[0])), r(Math.min(start[1], end[1])), r(Math.max(start[0], end[0])), r(Math.max(start[1], end[1]))];
  };

  $effect(() => {
    const el: HTMLElement = canvas.el;
    // Recorte en curso.
    let area: { index: number; start: [number, number]; end: [number, number]; mark: HTMLElement } | null = null;

    const down = (ev: PointerEvent) => {
      if (ev.button !== 0 || canvas.tool !== TOOLS.AREA_OCR) return;
      const box = el.getBoundingClientRect();
      if (ev.clientX - box.left >= el.clientWidth || ev.clientY - box.top >= el.clientHeight) return; // barra de desplazamiento
      const at = canvas.pageAt(ev.clientX, ev.clientY);
      if (!at) return;
      ev.preventDefault();
      const start = clamp(at.index, [at.x, at.y]);
      area = { index: at.index, start, end: start, mark: canvas.addMark(at.index, [...start, ...start], 'ocr-area') };
      el.setPointerCapture(ev.pointerId);
    };
    const move = (ev: PointerEvent) => {
      if (!area) return;
      area.end = clamp(area.index, canvas.pointOn(area.index, ev.clientX, ev.clientY));
      const rect = rectOf(area);
      const [pw, ph] = canvas.sizes[area.index];
      Object.assign(area.mark.style, {
        left: `${(rect[0] / pw) * 100}%`, top: `${(rect[1] / ph) * 100}%`,
        width: `${((rect[2] - rect[0]) / pw) * 100}%`, height: `${((rect[3] - rect[1]) / ph) * 100}%`,
      });
    };
    const up = () => {
      if (!area) return;
      const done = area;
      area = null;
      done.mark.remove();
      setTool(TOOLS.HAND); // como Qt: tras el recorte, a la mano
      const rect = rectOf(done);
      if (rect[2] - rect[0] < MIN_AREA || rect[3] - rect[1] < MIN_AREA) return;
      withBusy(T.areaMode, async () => {
        await syncText([done.index]);
        const result = await recognizer.area(done.index, rect);
        showResult(result, T.areaDone);
        text = result.text.trim() ? result.text : T.areaEmpty;
      });
    };
    const cancel = () => {
      area?.mark.remove();
      area = null;
    };

    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', cancel);
    return () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', cancel);
    };
  });

  // ── Lotes ──────────────────────────────────────────────────────────────
  async function openBatch() {
    if (busy) return;
    await syncText(); // mientras está abierto, las páginas no cambian
    const result = await openModal<string>(OcrBatchDialog, {
      docId,
      recognize: (index: number) => recognizer.page(index),
      total: canvas.pageCount,
      setBusy: (value: boolean) => (busy = value),
      onPage(index: number, pageResult: OcrResult) {
        setBoxes(index, pageResult.boxes);
        changed(index);
      },
    });
    if (result === null) return;
    if (active) load();
    openModal(OcrResultDialog, { docId, text: result });
  }
</script>

{#snippet tool(icon: string, label: string, title: string, onclick: () => void)}
  <button class="btn btn--sm ocr-panel__tool" type="button" {title} disabled={busy} {onclick}><Icon name={icon} size={15} />{label}</button>
{/snippet}

<div class="ocr-panel">
  <div class="ocr-panel__head">
    <span class="ocr-panel__icon"><Icon name="scan-text" size={20} /></span>
    <h2 class="heading">{T.title}</h2>
    <span class="grow"></span>
    <button class="btn btn--icon btn--sm" type="button" title={T.close} aria-label={T.close} onclick={close}><Icon name="x" /></button>
  </div>
  <div class="ocr-panel__row">
    <span class="ocr-chip ocr-chip--accent">{mode}</span>
    <span class="ocr-chip">{T.kind(kind)}</span>
  </div>
  <div class="ocr-panel__metrics">
    <div class="ocr-metric">
      <div class="ocr-metric__top"><Icon name="timer" /><strong class="ocr-metric__value">{time}</strong></div>
      <span class="caption">{T.time}</span>
    </div>
    <div class="ocr-metric">
      <div class="ocr-metric__top"><Icon name="hash" /><strong class="ocr-metric__value">{segments}</strong></div>
      <span class="caption">{T.segments}</span>
    </div>
  </div>
  <button class="btn btn--success btn--block" type="button" disabled={busy} onclick={runPage}>
    <Icon name="play" />{T.runPage}
  </button>
  <div class="ocr-panel__row">
    {@render tool('crop', T.area, T.areaTip, startArea)}
    {@render tool('rotate-cw', T.orient, T.orientTip, orient)}
    {@render tool('files', T.batch, T.batchTip, openBatch)}
  </div>
  <Checkbox label={T.showBoxes} bind:checked={showBoxes} />
  <div class="ocr-panel__row">
    <h3 class="heading">{T.text}</h3>
    <span class="grow"></span>
    <button class="btn btn--icon btn--sm" type="button" title={T.copy} aria-label={T.copy} onclick={copy}>
      <Icon name="copy" />
    </button>
  </div>
  <textarea class="input textarea ocr-panel__text" readonly aria-label={T.text} value={text}
            placeholder={T.placeholder}></textarea>
  <div class="progress progress--busy" hidden={!busy}><span></span></div>
</div>
