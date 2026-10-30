<!--
  Pestaña «OCR» del panel lateral (ocr_panel.py y ocr_worker.py en Qt): OCR de la
  página actual, de un recorte y por lotes, cajas del texto reconocido en el lienzo y
  texto extraído. El reconocimiento lo hace el servicio `ocr`; las palabras quedan en
  el documento abierto y entran en su capa de texto, así se pueden seleccionar y buscar.
-->
<script>
  import { call } from '$lib/api.js';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Icon from '$lib/Icon.svelte';
  import { openModal, setStatus, toast } from '$lib/ui.js';
  import { TOOLS } from './canvas.js';
  import OcrBatchDialog from './OcrBatchDialog.svelte';
  import OcrResultDialog from './OcrResultDialog.svelte';

  const MIN_AREA = 4; // pt: un recorte más pequeño es un clic, no un rectángulo
  const NO_TEXT = "Página sin texto digital detectable. Haz clic en 'Procesar Página Actual' o 'Recorte'.";

  /**
   * `page`: página actual; `active`: la pestaña está a la vista (solo entonces se pide el
   * texto de cada página); `changed(index)`: el texto de la página cambió (selección y
   * búsqueda lo releen); `orient()`: corregir la orientación de la página actual.
   */
  let { canvas, docId, page, active, close, setTool, changed, orient } = $props();

  let mode = $state('Modo OCR');
  let kind = $state('-');
  let time = $state('-');
  let segments = $state('-');
  let text = $state('');
  let busy = $state(false);
  let showBoxes = $state(false); // apagado por defecto, como en Qt: cubría cada página de cajas verdes
  let boxes = $state.raw(new Map()); // página -> cajas del último resultado
  let run = 0; // descarta respuestas de páginas anteriores

  const seconds = (ms) => `${(ms / 1000).toFixed(1)} s`;

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
    const marks = rects.map((rect) => canvas.addMark(page, rect, 'ocr-box'));
    return () => marks.forEach((mark) => mark.remove());
  });

  function setBoxes(index, rects) {
    boxes = new Map(boxes).set(index, rects);
  }

  async function load(index = page) {
    const mine = ++run;
    try {
      const result = await call('ocr.page_text', docId, index);
      if (mine !== run) return;
      kind = result.kind;
      segments = String(result.segments);
      text = result.text || NO_TEXT;
      setBoxes(index, result.boxes);
    } catch (err) {
      if (mine === run && err.code !== 'bad_page') toast(err.message, 'danger');
    }
  }

  /** Muestra un resultado de `ocr.page` u `ocr.area` y avisa de que cambió el texto de la página. */
  function showResult(result, label) {
    run++; // una carga de texto pendiente ya no vale
    time = seconds(result.elapsed_ms);
    segments = String(result.segments);
    mode = label;
    setBoxes(result.page, result.boxes);
    changed(result.page);
  }

  async function withBusy(label, fn) {
    if (busy) return;
    busy = true;
    const previous = mode;
    mode = label;
    try {
      await fn();
    } catch (err) {
      mode = previous;
      if (err.code !== 'stale') text = err.message;
      toast(err.message, 'danger');
    } finally {
      busy = false;
    }
  }

  function runPage() {
    const index = page;
    withBusy('Procesando OCR...', async () => {
      const result = await call('ocr.page', docId, index);
      showResult(result, `Modo ${result.mode}`);
      kind = result.kind;
      if (index === page) text = result.text || '(No se detectó texto en la página)';
    });
  }

  function copy() {
    const value = text.trim();
    if (!value || value === NO_TEXT) return;
    navigator.clipboard.writeText(value)
      .then(() => setStatus('Texto extraído copiado al portapapeles'))
      .catch((err) => toast(`No se pudo copiar: ${err.message}`, 'danger'));
  }

  // ── Recorte ────────────────────────────────────────────────────────────
  function startArea() {
    setTool(TOOLS.AREA_OCR);
    setStatus('Arrastra un rectángulo sobre el área del documento que deseas reconocer con OCR.');
  }

  const clamp = (index, [x, y]) => {
    const [w, ht] = canvas.sizes[index];
    return [Math.min(w, Math.max(0, x)), Math.min(ht, Math.max(0, y))];
  };

  const rectOf = ({ start, end }) => {
    const r = (v) => Math.round(v * 100) / 100;
    return [r(Math.min(start[0], end[0])), r(Math.min(start[1], end[1])), r(Math.max(start[0], end[0])), r(Math.max(start[1], end[1]))];
  };

  $effect(() => {
    const el = canvas.el;
    let area = null; // recorte en curso: { index, start, end, mark }

    const down = (ev) => {
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
    const move = (ev) => {
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
      withBusy('Recorte OCR...', async () => {
        const result = await call('ocr.area', docId, done.index, rect);
        showResult(result, 'Recorte OCR');
        text = result.text.trim() ? result.text : '(No se detectó texto en el área seleccionada)';
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
    const result = await openModal(OcrBatchDialog, {
      docId,
      total: canvas.pageCount,
      setBusy: (value) => (busy = value),
      onPage(index, pageResult) {
        setBoxes(index, pageResult.boxes);
        changed(index);
      },
    });
    if (result === null) return;
    if (active) load();
    openModal(OcrResultDialog, { docId, text: result });
  }
</script>

{#snippet tool(icon, label, title, onclick)}
  <button class="btn btn--sm ocr-panel__tool" type="button" {title} disabled={busy} {onclick}><Icon name={icon} size={15} />{label}</button>
{/snippet}

<div class="ocr-panel">
  <div class="ocr-panel__head">
    <span class="ocr-panel__icon"><Icon name="scan-text" size={20} /></span>
    <h2 class="heading">Motor OCR</h2>
    <span class="grow"></span>
    <button class="btn btn--icon btn--sm" type="button" title="Cerrar" aria-label="Cerrar" onclick={close}><Icon name="x" /></button>
  </div>
  <div class="ocr-panel__row">
    <span class="ocr-chip ocr-chip--accent">{mode}</span>
    <span class="ocr-chip">Tipo: {kind}</span>
  </div>
  <div class="ocr-panel__metrics">
    <div class="ocr-metric">
      <div class="ocr-metric__top"><Icon name="timer" /><strong class="ocr-metric__value">{time}</strong></div>
      <span class="caption">Tiempo</span>
    </div>
    <div class="ocr-metric">
      <div class="ocr-metric__top"><Icon name="hash" /><strong class="ocr-metric__value">{segments}</strong></div>
      <span class="caption">Segmentos</span>
    </div>
  </div>
  <button class="btn btn--success btn--block" type="button" disabled={busy} onclick={runPage}>
    <Icon name="play" />Procesar Página Actual
  </button>
  <div class="ocr-panel__row">
    {@render tool('crop', 'Recorte', 'Arrastra un rectángulo sobre el lienzo para extraer OCR de esa área', startArea)}
    {@render tool('rotate-cw', 'Orientar', 'Detectar y corregir automáticamente la orientación de la página', orient)}
    {@render tool('files', 'Documento', 'Procesar OCR por lotes en todo el documento o páginas seleccionadas', openBatch)}
  </div>
  <Checkbox label="Mostrar cajas de texto en lienzo" bind:checked={showBoxes} />
  <div class="ocr-panel__row">
    <h3 class="heading">Texto extraído</h3>
    <span class="grow"></span>
    <button class="btn btn--icon btn--sm" type="button" title="Copiar texto extraído" aria-label="Copiar texto extraído" onclick={copy}>
      <Icon name="copy" />
    </button>
  </div>
  <textarea class="input textarea ocr-panel__text" readonly aria-label="Texto extraído" value={text}
            placeholder="Ejecuta OCR para ver el texto extraído aquí..."></textarea>
  <div class="progress progress--busy" hidden={!busy}><span></span></div>
</div>
