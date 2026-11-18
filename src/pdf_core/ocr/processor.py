"""Hybrid OCR utilities: native PDF text + OCR only on image regions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np

from pdf_core.ocr.paddle import OrientationClassifier, TextRecognizer
from pdf_core.pdf import Document, Page, Rect

_SCALE_FOR_OCR = 2.0
_MAX_OCR_PX = 2000  # cap longest edge to avoid huge pixmaps on large pages
_CLASSIFIER_SURE = 0.90  # por debajo, un «0°» del clasificador se comprueba con OCR
_SMALL_SCALE = 0.8  # píxeles por punto de la imagen con la que se clasifica la orientación


@dataclass
class OCRSegment:
    """
    Represents a segment of text extracted from a page.
    """
    text: str
    source: str  # native | ocr
    bbox: Rect


@dataclass
class OCRDetection: 
    """
    Represents a single OCR detection with confidence score.
    """
    text: str
    score: float
    source: str  # ocr
    bbox: Rect


@dataclass
class OCRPageResult:
    """
    Represents the result of processing a single page, including its classification,
    the segments of text found, and the time taken.
    """
    page_kind: str  # scanned | native | hybrid
    doc_kind: str   # scanned | native | hybrid
    mode_label: str  # OCR | Nativo | Hibrido
    elapsed_ms: float
    segments: list[OCRSegment]
    detections: list[OCRDetection]


@dataclass
class PreparedPage:
    """Fase 1 del OCR de una página: clasificación + texto nativo + regiones ya
    RASTERIZADAS, sin inferencia.

    Es todo lo que necesita tocar el documento: el llamador la produce
    bajo su lock de documento (``prepare_page``) y corre la inferencia —lo
    lento— FUERA del lock (``recognize_page``), de modo que el render/scroll
    del visor no se quede esperando el lock durante los segundos que tarda el
    modelo.
    """
    page_kind: str
    doc_kind: str
    native_segments: list[OCRSegment]
    regions: list[tuple[Rect, float, np.ndarray]]   # (rect, scale, img)
    start: float   # perf_counter() al iniciar, para el tiempo total reportado


class OCRProcessor:

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        self.model_root = self.workspace_root / "modelos"
        self._predictor: TextRecognizer | None = None
        self._orientation_predictor: OrientationClassifier | None = None
        # Keyed by doc.name (file path) so different documents don't share state.
        self._doc_kind_cache: dict[str, str] = {}

    @property
    def predictor(self) -> TextRecognizer:
        """Detección + reconocimiento PP-OCRv6 (ver :mod:`pdf_core.ocr.paddle`)."""
        if self._predictor is None:
            self._predictor = TextRecognizer()
        return self._predictor

    @property
    def orientation_predictor(self) -> OrientationClassifier:
        """Clasificador de orientación de documento (PP-LCNet, ~7 MB).

        Clasifica una imagen de página completa en 0°, 90°, 180° o 270°.
        Se carga de forma perezosa independientemente del modelo OCR principal,
        por lo que puede usarse sin cargar detección+reconocimiento.
        """
        if self._orientation_predictor is None:
            self._orientation_predictor = OrientationClassifier()
        return self._orientation_predictor

    def release_predictor(self) -> None:
        """Free OCR model memory after idle periods."""
        self._predictor = None  # las sesiones de onnxruntime se liberan con el objeto

    def release_orientation_predictor(self) -> None:
        """Libera el modelo de orientación de la memoria."""
        self._orientation_predictor = None

    @staticmethod
    def detect_orientation_native(page: Page) -> int:
        """Detecta la orientación de una página nativa por el sentido de su texto.

        Si el sentido dominante en la vista no es (1, 0) (de izquierda a derecha), devuelve el
        ángulo de corrección. Cada carácter cuenta igual, así los titulares cortos no
        distorsionan las páginas con mucho cuerpo de texto. Los cuatro casos:

          - ( 1,  0): sin corrección (0°)
          - (-1,  0): corrección 180°  (texto invertido)
          - ( 0, -1): corrección  90°  (texto sube en pantalla)
          - ( 0, +1): corrección 270°  (texto baja en pantalla)
        """
        try:
            wx, wy = page.text_direction()
        except Exception:
            return 0

        if wx == 0.0 and wy == 0.0:
            return 0

        if abs(wx) >= abs(wy):
            return 0 if wx >= 0 else 180
        return 90 if wy < 0 else 270

    def score_orientation_classifier(self, img: np.ndarray) -> int:
        """Detecta la orientación con el clasificador de documentos PP-LCNet.

        Devuelve 0, 90, 180 o 270 (grados a SUMAR, para
        ``page.set_rotation((page.rotation + angle) % 360)``); devuelve 0 si la
        confianza es baja o el modelo falla.
        """
        angle, conf = self.classify_orientation(img)
        return angle if conf >= 0.50 else 0

    def classify_orientation(self, img: np.ndarray) -> tuple[int, float]:
        """Como :meth:`score_orientation_classifier`, pero devuelve también la
        confianza: ``(grados a sumar, confianza 0–1)``; ``(0, 0.0)`` si el modelo falla."""
        try:
            return self.orientation_predictor(img)
        except Exception:
            return 0, 0.0

    def _run_predictor(self, img: np.ndarray) -> tuple[list[tuple[Rect, str, float]], float]:
        """ Regresa una lista de tuplas (rectángulo, texto, puntuación) para cada palabra detectada en la imagen, junto con el tiempo que tomó ejecutar el predictor.
        """
        h, w = img.shape[:2]
        if h == 0 or w == 0:  # imagen degenerada: nada que reconocer
            return [], 0.0

        start = perf_counter()
        found = self.predictor(img)
        elapsed = perf_counter() - start
        words = [(Rect(wd.x0, wd.y0, wd.x1, wd.y1), wd.text, wd.score) for wd in found if wd.text.strip()]
        return words, elapsed

    def render_orientation_probe(self, doc: Document, page_num: int) -> np.ndarray:
        """Rasteriza la página para sondear su orientación (fase BAJO lock)."""
        page = doc[page_num]
        longest = max(page.rect.width, page.rect.height)
        scale = min(1.5, 1400.0 / max(1.0, longest))
        return page.render(scale)

    def probe_orientation(
        self, doc: Document, page_num: int
    ) -> tuple[np.ndarray, int | None]:
        """Renderiza la sonda y detecta orientación nativa en una sola pasada.

        Retorna ``(imagen, angulo_nativo_o_None)``.
        Si la página tiene texto extraíble, devuelve el ángulo de corrección
        calculado directamente de los vectores de dirección (exacto, sin modelo).
        Si la página es solo imagen (escaneo), devuelve ``None`` para que el
        llamador use el clasificador.
        """
        page = doc[page_num]
        longest = max(page.rect.width, page.rect.height)
        scale = min(1.5, 1400.0 / max(1.0, longest))
        img = page.render(scale)
        native_angle: int | None = None
        if not self.page_needs_ocr(page):
            native_angle = self.detect_orientation_native(page)
        return img, native_angle

    def detect_orientation(self, doc: Document, page_num: int) -> int:
        """Conveniencia: sondeo + puntuación en un paso (sin lock que liberar)."""
        return self.score_orientation(self.render_orientation_probe(doc, page_num))

    @staticmethod
    def score_orientation_fast(img: np.ndarray) -> int:
        """Detección de orientación rápida sin modelo OCR (< 15 ms).

        Señales usadas:

        1. **Varianza de perfiles** (h_var vs v_var): detecta 90°/270° vs 0°/180°.
           Alta fiabilidad para páginas con texto claramente horizontal o vertical.

        2. **Posición del primer borde de texto** (``_first_text_row``): dentro del
           par 90°/270° determina la dirección correcta. Para 0°/180° mide
           ``pos_asym = s0 - s180``; valor muy positivo → candidato a 180°.

        3. **Sesgo de línea base** (``_baseline_bias``): en texto latino derecho (0°)
           el pico de densidad queda en la mitad INFERIOR de cada banda de texto
           (línea base cerca del fondo de las letras). En 180° ese pico sube a la
           mitad SUPERIOR. Solo se usa en la zona central de la imagen para evitar
           artefactos de bordes de escaneado.

        Ambas señales (2 y 3) deben coincidir para declarar 180°, lo que reduce
        drásticamente los falsos positivos en documentos escaneados ruidosos.
        """
        # ── Preprocesado ──────────────────────────────────────────────────────
        if img.ndim == 3:
            gray = np.dot(img[..., :3].astype(np.float32), [0.299, 0.587, 0.114])
        else:
            gray = img.astype(np.float32)

        mean_val = float(gray.mean())
        if mean_val < 10 or mean_val > 245:
            return 0  # página en blanco o completamente oscura

        # Binarización robusta para escáneos: usa el percentil 90 como estimación
        # del fondo. A diferencia de la media, el percentil 90 corresponde al fondo
        # real incluso en páginas con fondo grisáceo o amarillento. Los píxeles de
        # tinta deben ser al menos 38% más oscuros que el fondo estimado.
        background = float(np.percentile(gray, 90))
        ink_thresh = max(50.0, background * 0.62)
        binary = (gray < ink_thresh).astype(np.float32)
        ink_frac = float(binary.mean())
        # Si hay demasiado poco contenido oscuro (página casi en blanco) o demasiado
        # (fondo oscuro, no tinta puntual de texto), la señal no es fiable.
        if ink_frac < 0.004 or ink_frac > 0.30:
            return 0

        # ── Auxiliares ────────────────────────────────────────────────────────

        def _first_text_row(b: np.ndarray) -> float:
            """Posición relativa (0–1) de la primera fila con densidad de tinta
            significativa. Umbral al 40% del máximo para ignorar ruido de escaneado."""
            h_proj = b.sum(axis=1)
            ksz = max(1, len(h_proj) // 30)
            smooth = np.convolve(h_proj, np.ones(ksz) / ksz, mode='same')
            thr = float(smooth.max()) * 0.40
            for i, v in enumerate(smooth):
                if v > thr:
                    return i / max(1, len(smooth))
            return 0.5

        def _baseline_bias(b: np.ndarray) -> float:
            """Posición media relativa del pico de densidad dentro de cada
            banda de texto (0 = tope, 1 = fondo).

            Operando sobre la zona CENTRAL de la imagen (excluyendo el 12% superior
            e inferior) se evitan los artefactos de borde de escaneado (sombras
            oscuras en los márgenes) que distorsionan el análisis.

            En texto latino 0°: el pico (baseline) queda en la mitad INFERIOR
            de cada banda → resultado > 0.55.
            En texto 180°: el pico pasa a la mitad SUPERIOR → resultado < 0.42.
            """
            H_full = b.shape[0]
            margin = max(4, H_full // 8)  # excluir ~12% en cada extremo
            b = b[margin: H_full - margin]
            H = b.shape[0]
            if H < 20:
                return float("nan")

            h = b.sum(axis=1)
            ksz = max(3, H // 50)
            smooth = np.convolve(h, np.ones(ksz) / ksz, mode='same')
            thr = float(smooth.max()) * 0.22

            positions: list[float] = []
            i = 0
            while i < H:
                if smooth[i] > thr:
                    j = i + 1
                    while j < H and smooth[j] > thr:
                        j += 1
                    band_h = j - i
                    if 5 <= band_h <= H // 3:
                        band = h[i:j]
                        argmax_rel = float(np.argmax(band)) / max(1, band_h - 1)
                        positions.append(argmax_rel)
                    i = j
                else:
                    i += 1

            if len(positions) < 2:
                return float("nan")
            return float(np.mean(positions))

        # ── Señal 1: varianza de perfiles ─────────────────────────────────────
        h_var = float(np.var(binary.sum(axis=1)))
        v_var = float(np.var(binary.sum(axis=0)))
        _RATIO = 1.8

        if v_var > h_var * _RATIO:
            # Texto en columnas verticales → 90° o 270°.
            s270 = _first_text_row(np.rot90(binary, k=1))
            s90  = _first_text_row(np.rot90(binary, k=3))
            return 270 if s270 < s90 else 90

        if h_var > v_var * _RATIO:
            # Texto horizontal → 0° o 180°.
            # Ambas señales deben coincidir para declarar 180°.
            #
            # pos_asym = s0 - s180:
            #   · 0°:   s0 pequeño, s180 grande → pos_asym muy NEGATIVO (−0.6 típico)
            #   · 180°: s0 grande, s180 pequeño → pos_asym muy POSITIVO (+0.6 típico)
            #
            # bias (sesgo de línea base en zona central):
            #   · 0°:   pico cerca del fondo de cada banda → bias > 0.55
            #   · 180°: pico cerca del tope de cada banda  → bias < 0.42
            s0       = _first_text_row(binary)
            s180     = _first_text_row(np.rot90(binary, k=2))
            bias     = _baseline_bias(binary)
            pos_asym = s0 - s180

            if pos_asym > 0.35 and not np.isnan(bias) and bias < 0.42:
                return 180

            return 0

        return 0  # señal ambigua

    def score_orientation(self, base: np.ndarray) -> int:
        """Detecta cuántos grados (0/90/180/270) hay que SUMAR a la rotación
        actual de la página para que el texto quede derecho (fase SIN lock).

        Pensado para escaneos cuyo *contenido* está girado pero sin entrada
        ``/Rotate`` (la rotación es 0 y la página se ve de lado).
        Reutiliza los modelos OCR ya incluidos (sin descargas): puntúa las 4
        orientaciones por la suma de confianzas de las palabras reconocidas; la
        orientación correcta produce palabras reales con alta confianza.
        Devuelve 0 si ya está derecha o si no hay señal suficiente.
        """
        # np.rot90(k) gira la imagen en sentido ANTIHORARIO; /Rotate gira en
        # sentido HORARIO. Para reproducir con page.set_rotation el mismo efecto
        # que np.rot90(base, k) hay que sumar ((4-k)%4)*90 grados horarios.
        _MIN_CONF  = 0.40   # umbral de confianza por palabra (filtra ruido)
        _MIN_LEN   = 2      # mínimo de caracteres (una sola letra = casi siempre falso positivo)
        _MIN_WORDS = 3      # mínimo de palabras reales para tener señal fiable

        candidates = ((0, 0), (1, 270), (2, 180), (3, 90))
        best_angle, best_score, second = 0, -1.0, 0.0
        best_count = 0
        for k, angle in candidates:
            img = np.rot90(base, k=k).copy() if k else base
            words, _ = self._run_predictor(img)
            # Filtrar ruido: exigir longitud mínima y confianza mínima.
            # Ponderar por longitud: "Document" contribuye más que "hi".
            real = [(r, t, s) for r, t, s in words if len(t) >= _MIN_LEN and s >= _MIN_CONF]
            score = sum(s * (len(t) - 1) for _, t, s in real)
            if score > best_score:
                second = best_score
                best_score, best_angle, best_count = score, angle, len(real)
            elif score > second:
                second = score
        del base

        # Sin señal (página casi en blanco o sin texto legible en ninguna orientación)
        if best_count < _MIN_WORDS or best_score <= 0.0:
            return 0
        # Margen adaptativo: con muchas palabras claras basta un 10 % de ventaja;
        # con poca señal exigimos 20 % para no confundir páginas mixtas o imágenes.
        margin = 1.10 if best_count >= 8 else 1.20
        if best_score < second * margin:
            return 0
        return best_angle

    def render_orientation_probes(
        self, doc: Document, page_nums: list[int]
    ) -> list[np.ndarray]:
        """Rasteriza varias páginas para el sondeo multi-página (fase BAJO lock)."""
        images: list[np.ndarray] = []
        for pn in page_nums:
            page = doc[pn]
            longest = max(page.rect.width, page.rect.height)
            scale = min(1.5, 1400.0 / max(1.0, longest))
            images.append(page.render(scale))
        return images

    def probe_pages_for_orientation(
        self, doc: Document, page_nums: list[int]
    ) -> list[tuple[np.ndarray, int | None]]:
        """Rasteriza y detecta orientación nativa para varias páginas (BAJO lock).

        Por cada página retorna ``(imagen, angulo_nativo_o_None)``:
        - Si la página tiene texto extraíble: ``native_angle`` es el ángulo de
          corrección calculado de los vectores de dirección (exacto, sin modelo).
        - Si la página es un escaneo: ``native_angle`` es ``None`` → el llamador
          debe usar el clasificador.
        """
        results: list[tuple[np.ndarray, int | None]] = []
        for pn in page_nums:
            page = doc[pn]
            longest = max(page.rect.width, page.rect.height)
            scale = min(1.5, 1400.0 / max(1.0, longest))
            img = page.render(scale)
            native_angle: int | None = None
            if not self.page_needs_ocr(page):
                native_angle = self.detect_orientation_native(page)
            results.append((img, native_angle))
        return results

    def score_orientation_multi(self, images: list[np.ndarray]) -> int:
        """Vota la orientación entre varias imágenes de página para mayor robustez.

        Devuelve el ángulo que aparece en ≥ 50 % de las páginas sondeadas,
        o 0 si no hay consenso suficiente (incluye páginas que devuelven 0
        porque ya están derechas o sin señal).
        """
        if not images:
            return 0
        from collections import Counter
        votes: Counter[int] = Counter()
        for img in images:
            votes[self.score_orientation(img)] += 1

        total = sum(votes.values())
        non_zero = {a: c for a, c in votes.items() if a != 0}
        if not non_zero:
            return 0

        best_angle, best_count = max(non_zero.items(), key=lambda x: x[1])
        # Exigir que al menos la mitad de las páginas sondeadas coincidan
        if best_count / total >= 0.5:
            return best_angle
        return 0

    def get_doc_kind(self, doc: Document) -> str:
        """Clasificar el documento como 'nativo', 'escaneado' o 'híbrido' según el contenido de sus páginas.
         - 'nativo' si tiene al menos una página con texto extraíble y ninguna con imágenes.
         - 'escaneado' si tiene al menos una página con imágenes y ninguna con texto extraíble.
         - 'híbrido' si tiene al menos una página con texto extraíble y al menos una página con imágenes.
         - Si no tiene páginas con texto ni imágenes, se clasifica como 'escaneado' por defecto.
         - Solo se analizan las primeras 20 páginas para determinar el tipo de documento, para mejorar el rendimiento en documentos largos.
         -
        """
        key = doc.name or id(doc)
        if key in self._doc_kind_cache:
            return self._doc_kind_cache[key]

        text_pages = 0
        image_pages = 0
        max_pages = min(len(doc), 20)

        for i in range(max_pages):
            if text_pages > 0 and image_pages > 0:
                break  # already "hybrid" — no need to scan more pages
            page = doc[i]
            has_text = bool(page.text().strip())
            has_images = page.has_images()
            if has_text:
                text_pages += 1
            if has_images:
                image_pages += 1

        if text_pages > 0 and image_pages == 0:
            kind = "native"
        elif text_pages == 0 and image_pages > 0:
            kind = "scanned"
        elif text_pages == 0 and image_pages == 0:
            kind = "scanned"
        else:
            kind = "hybrid"

        self._doc_kind_cache[key] = kind
        return kind

    def page_kind(self, page: Page) -> str:
        """Clasificar la página según su contenido (ver :func:`kind_of`)."""
        return kind_of(bool(page.text().strip()), page.has_images())

    def page_needs_ocr(self, page: Page) -> bool:
        """Return True only when the page lacks extractable native text."""
        return not bool(page.text().strip())

    def _native_segments(self, page: Page) -> list[OCRSegment]:
        """Una por línea de texto nativo."""
        lines: dict[int, list[tuple[Rect, str]]] = {}
        for rect, text, line in page.words():
            lines.setdefault(line, []).append((rect, text))
        segments = []
        for words in lines.values():
            boxes = [rect for rect, _ in words]
            segments.append(OCRSegment(
                text=" ".join(text for _, text in words),
                source="native",
                bbox=Rect(min(r.x0 for r in boxes), min(r.y0 for r in boxes),
                          max(r.x1 for r in boxes), max(r.y1 for r in boxes)),
            ))
        return segments

    def _image_regions(self, page: Page) -> list[Rect]:
        regions: list[Rect] = []
        for box in page.image_rects():
            # Recortadas a la página: las que se salen de ella darían una imagen degenerada.
            rect = box & page.rect
            if rect.is_empty or rect.width < 8 or rect.height < 8:
                continue
            regions.append(rect)

        # Some scanned PDFs have no image blocks; OCR the whole page as fallback.
        if not regions:
            regions.append(page.rect)
        return regions

    @staticmethod
    def _ocr_scale(rect: Rect) -> float:
        longest = max(rect.width, rect.height)
        scale = _SCALE_FOR_OCR
        if longest * scale > _MAX_OCR_PX:
            scale = _MAX_OCR_PX / longest
        return max(scale, 1.0)

    def prepare_page(self, doc: Document, page_num: int, force_ocr: bool = False) -> PreparedPage:
        """Fase 1 (BAJO el lock del documento): clasificar la página, extraer el
        texto nativo y rasterizar las regiones a OCRear. Es rápida (decenas de
        ms); todo lo que toca ``doc`` ocurre aquí."""
        page = doc[page_num]
        doc_kind = self.get_doc_kind(doc)
        page_kind = self.page_kind(page)

        start = perf_counter()
        native_segments = self._native_segments(page)
        regions: list[tuple[Rect, float, np.ndarray]] = []
        if force_ocr or page_kind in ("hybrid", "scanned"):
            for rect in self._image_regions(page):
                scale = self._ocr_scale(rect)
                img = page.render(scale, clip=rect)
                if img.size:
                    regions.append((rect, scale, img))

        return PreparedPage(
            page_kind=page_kind,
            doc_kind=doc_kind,
            native_segments=native_segments,
            regions=regions,
            start=start,
        )

    def recognize_regions(self, regions: list[tuple[Rect, float, np.ndarray]]) -> tuple[list[OCRDetection], float]:
        """Inferencia del modelo sobre imágenes ya dibujadas — los segundos lentos del OCR.

        Cada región es ``(rect, escala, imagen)``: la imagen de ``rect`` (coordenadas de vista) a
        ``escala`` píxeles por punto. Devuelve las palabras en coordenadas de vista y los segundos
        de inferencia. No toca ningún documento: el visor le pasa las imágenes que dibuja su motor.
        """
        detections: list[OCRDetection] = []
        elapsed = 0.0
        for rect, scale, img in regions:
            words, seconds = self._run_predictor(img)
            elapsed += seconds
            for px_rect, text, score in words:
                bbox = Rect(rect.x0 + px_rect.x0 / scale, rect.y0 + px_rect.y0 / scale,
                            rect.x0 + px_rect.x1 / scale, rect.y0 + px_rect.y1 / scale)
                detections.append(OCRDetection(text=text, score=score, source="ocr", bbox=bbox))
        return detections, elapsed

    def recognize_page(self, prep: PreparedPage) -> OCRPageResult:
        """Fase 2 (SIN lock): inferencia del modelo sobre las imágenes ya
        rasterizadas — los segundos lentos del OCR. No toca el documento."""
        detections, ocr_elapsed = self.recognize_regions(prep.regions)
        prep.regions.clear()  # liberar las imágenes rasterizadas cuanto antes
        ocr_segments = [OCRSegment(text=d.text, source="ocr", bbox=d.bbox) for d in detections]

        segments = [*prep.native_segments, *ocr_segments]
        segments.sort(key=lambda s: (s.bbox.y0, s.bbox.x0))

        mode = mode_of(bool(prep.native_segments), bool(ocr_segments))
        wall_elapsed = perf_counter() - prep.start
        elapsed_ms = max(wall_elapsed, ocr_elapsed) * 1000

        return OCRPageResult(
            page_kind=prep.page_kind,
            doc_kind=prep.doc_kind,
            mode_label=mode,
            elapsed_ms=elapsed_ms,
            segments=segments,
            detections=detections,
        )

    def prepare_area(self, doc: Document, page_num: int, rect: Rect) -> PreparedPage:
        """Como :meth:`prepare_page`, pero solo el rectángulo ``rect`` (coordenadas de la
        página tal como se ve) y sin texto nativo: el OCR de un recorte."""
        page = doc[page_num]
        clip = Rect(*rect) & page.rect
        regions: list[tuple[Rect, float, np.ndarray]] = []
        if not clip.is_empty and clip.width >= 4 and clip.height >= 4:
            # Los recortes suelen ser pequeños: más resolución que una página entera.
            scale = min(2.5, max(1.5, 1600.0 / max(clip.width, clip.height)))
            img = page.render(scale, clip=clip)
            if img.size:
                regions.append((clip, scale, img))
        return PreparedPage(
            page_kind=self.page_kind(page),
            doc_kind=self.get_doc_kind(doc),
            native_segments=[],
            regions=regions,
            start=perf_counter(),
        )

    def correction_angle(self, page: Page) -> int:
        """Grados a sumar a la rotación de ``page`` para dejarla derecha (0, 90, 180 o 270).

        Si tiene texto nativo, por su dirección. Si es un escaneo, como el visor
        Flet: primero la varianza de perfiles (90°/270°, sin modelo) y después el
        clasificador de orientación. Si el clasificador dice «derecha» sin estar
        seguro (p. ej. una página con poco texto), decide el OCR en las cuatro
        orientaciones (:meth:`score_orientation`), más lento pero fiable.
        """
        angle = self.detect_orientation_native(page)
        if angle or len(page.text().strip()) >= 30:
            return angle % 360
        return self.image_correction(page.render(_SMALL_SCALE), self.render_orientation_probe(page.parent, page.number))

    def image_correction(self, small: np.ndarray, probe: np.ndarray) -> int:
        """Grados a sumar a la rotación de una página escaneada para dejarla derecha, por su imagen.

        ``small`` es la página a :data:`_SMALL_SCALE` píxeles por punto y ``probe``, la sonda (ver
        :meth:`render_orientation_probe`): primero la varianza de perfiles (90°/270°, sin
        modelo) y después el clasificador; si dice «derecha» sin estar seguro (p. ej. una página
        con poco texto), decide el OCR en las cuatro orientaciones sobre la sonda
        (:meth:`score_orientation`), más lento pero fiable.
        """
        angle = self.score_orientation_fast(small)
        if angle:
            return angle % 360
        angle, conf = self.classify_orientation(small)
        if conf < 0.50:
            angle = 0
        if angle == 0 and conf < _CLASSIFIER_SURE:
            angle = self.score_orientation(probe)
        return angle % 360

    def process_page(self, doc: Document, page_num: int, force_ocr: bool = False) -> OCRPageResult:
        """Conveniencia (todo en uno) para llamadores sin lock que liberar —
        p. ej. el extractor por lotes. El visor usa las dos fases por separado
        para no retener su ``_doc_lock`` durante la inferencia."""
        return self.recognize_page(self.prepare_page(doc, page_num, force_ocr))


def kind_of(has_text: bool, has_images: bool) -> str:
    """Tipo de página por su contenido: ``native`` (solo texto extraíble), ``scanned`` (solo
    imágenes, o nada) o ``hybrid`` (las dos cosas)."""
    if has_text:
        return "hybrid" if has_images else "native"
    return "scanned"


def mode_of(native_text: bool, recognized: bool) -> str:
    """Cómo se obtuvo el texto de una página: ``Hibrido``, ``Nativo``, ``OCR`` o ``Sin texto``."""
    if native_text and recognized:
        return "Hibrido"
    if native_text:
        return "Nativo"
    return "OCR" if recognized else "Sin texto"
