"""Hybrid OCR utilities: native PDF text + OCR only on image regions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import fitz
import numpy as np


_SCALE_FOR_OCR = 2.0
_MAX_OCR_PX = 2000  # cap longest edge to avoid huge pixmaps on large pages


@dataclass
class OCRSegment:
    """
    Represents a segment of text extracted from a page.
    """
    text: str
    source: str  # native | ocr
    bbox: fitz.Rect


@dataclass
class OCRDetection: 
    """
    Represents a single OCR detection with confidence score.
    """
    text: str
    score: float
    source: str  # ocr
    bbox: fitz.Rect


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

    Es todo lo que necesita tocar el ``fitz.Document``: el llamador la produce
    bajo su lock de documento (``prepare_page``) y corre la inferencia —lo
    lento— FUERA del lock (``recognize_page``), de modo que el render/scroll
    del visor no se quede esperando el lock durante los segundos que tarda el
    modelo.
    """
    page_kind: str
    doc_kind: str
    native_segments: list[OCRSegment]
    regions: list[tuple[fitz.Rect, float, np.ndarray]]   # (rect, scale, img)
    start: float   # perf_counter() al iniciar, para el tiempo total reportado


class OCRProcessor:

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        self.model_root = self.workspace_root / "modelos"
        self._predictor: Any | None = None
        self._orientation_predictor: Any | None = None
        # Keyed by doc.name (file path) so different documents don't share state.
        self._doc_kind_cache: dict[str, str] = {}

    def _set_onnxtr_cache(self) -> None:
        os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
        bundled = Path(__file__).resolve().parents[2] / "assets" / "onnxtr_cache"
        if bundled.exists():
            os.environ["ONNXTR_CACHE_DIR"] = str(bundled)

    @property
    def predictor(self):
        if self._predictor is None:
            from onnxtr.models import ocr_predictor
            self._set_onnxtr_cache()
            self._predictor = ocr_predictor(
                det_arch="db_mobilenet_v3_large",
                reco_arch="crnn_mobilenet_v3_small",
                detect_language=False,
                load_in_8_bit=False,
            )
        return self._predictor

    @property
    def orientation_predictor(self):
        """Clasificador de orientación de página (MobileNetV3-small, ~5 MB).

        Clasifica una imagen de página completa en 0°, 90°, 180° o 270°.
        Se carga de forma perezosa independientemente del modelo OCR principal,
        por lo que puede usarse sin cargar detección+reconocimiento.
        """
        if self._orientation_predictor is None:
            from onnxtr.models import page_orientation_predictor
            self._set_onnxtr_cache()
            # No pasar pretrained=True: en v0.8.x se filtra incorrectamente
            # hasta Resize.__init__ y rompe la construcción del predictor.
            self._orientation_predictor = page_orientation_predictor()
        return self._orientation_predictor

    def release_predictor(self) -> None:
        """Free OCR model memory after idle periods."""
        predictor = self._predictor
        if predictor is None:
            return
        self._predictor = None
        close = getattr(predictor, "close", None)
        if callable(close):
            close()
        del predictor

    def release_orientation_predictor(self) -> None:
        """Libera el modelo de orientación de la memoria."""
        predictor = self._orientation_predictor
        if predictor is None:
            return
        self._orientation_predictor = None
        close = getattr(predictor, "close", None)
        if callable(close):
            close()
        del predictor

    @staticmethod
    def detect_orientation_native(page: "fitz.Page") -> int:
        """Detecta la orientación de una página nativa usando vectores de dirección.

        Estrategia: para cada línea de texto extrae su vector ``dir`` (espacio de
        contenido/pre-rotación) y lo lleva al espacio de pantalla multiplicando por
        ``page.rotation_matrix``.  Si la dirección dominante no es (1, 0) (texto
        fluyendo de izquierda a derecha), devuelve el ángulo de corrección necesario.

        Ponderación: cada línea contribuye proporcionalmente a su número de
        caracteres, de modo que los titulares cortos no distorsionen páginas
        con mucho cuerpo de texto.

        Cubre los cuatro casos:
          - display_dir ≈ ( 1,  0): sin corrección (0°)
          - display_dir ≈ (-1,  0): corrección 180°  (texto invertido)
          - display_dir ≈ ( 0, -1): corrección  90°  (texto sube en pantalla)
          - display_dir ≈ ( 0, +1): corrección 270°  (texto baja en pantalla)

        Ventaja sobre el enfoque de posición Y anterior: funciona aunque el texto
        ocupe toda la página (sin depender de un umbral de posición), y detecta
        también rotaciones de 90°/270°.
        """
        try:
            d = page.get_text("dict", flags=0)
        except Exception:
            return 0

        rm = page.rotation_matrix
        # Parte lineal (solo rotación, sin traslación): p1 - p0 cancela e,f.
        # Mismo patrón que _screen_delta_to_page() en annotations.py.
        origin = fitz.Point(0.0, 0.0) * rm
        wx, wy = 0.0, 0.0

        for block in d.get("blocks", []):
            if block.get("type") != 0:          # solo bloques de texto
                continue
            for line in block.get("lines", []):
                dir_vec = line.get("dir", (1.0, 0.0))
                n_chars = sum(len(s.get("text", "")) for s in line.get("spans", []))
                if n_chars == 0:
                    continue
                # Solo la parte rotacional de la matriz (sin traslación)
                p = fitz.Point(dir_vec[0], dir_vec[1]) * rm
                wx += (p.x - origin.x) * n_chars
                wy += (p.y - origin.y) * n_chars

        if wx == 0.0 and wy == 0.0:
            return 0

        if abs(wx) >= abs(wy):
            return 0 if wx >= 0 else 180
        return 90 if wy < 0 else 270

    def score_orientation_classifier(self, img: np.ndarray) -> int:
        """Detecta la orientación usando el clasificador MobileNetV3 de OnnxTR.

        La API de page_orientation_predictor (v0.8.x) devuelve una lista de
        3 sub-listas: [class_indices, angles, confidences], una entrada por
        imagen de entrada.

            pred([img])  →  [[class_idx], [angle_deg], [confidence]]

        Ejemplos reales (texto upright a cada ángulo):
            0°  → [[0], [   0], [0.98]]
            90° → [[1], [ -90], [0.99]]   (rot 90° CCW en imagen)
           180° → [[2], [ 180], [0.99]]
           270° → [[3], [  90], [1.00]]   (rot 90° CW en imagen)

        El campo `angle` ya es el valor correcto para pasar a
        ``page.set_rotation((page.rotation + angle) % 360)``  — salvo el
        signo para −90, pero en Python ``(rot + (−90)) % 360 == rot + 270``.

        Devuelve 0, 90, 180 o 270 (grados a SUMAR); devuelve 0 si la
        confianza es baja o el modelo falla.
        """
        try:
            result = self.orientation_predictor([img])
            # result = [class_list, angle_list, conf_list]
            if not result or len(result) < 3:
                return 0
            angle = int(result[1][0])   # ángulo de corrección (puede ser negativo)
            conf  = float(result[2][0]) # confianza 0–1
            if conf >= 0.50:
                return int(angle % 360)  # normalizar a 0–359
        except Exception:
            pass
        return 0

    @staticmethod
    def _geometry_to_pixel_rect(geometry: Any, width: int, height: int) -> fitz.Rect | None:
        if geometry is None:
            return None
        coords = np.asarray(geometry, dtype=float)
        if coords.ndim != 2 or coords.shape[1] != 2:
            return None

        xs = coords[:, 0]
        ys = coords[:, 1]

        # OnnxTR usually exports normalized coordinates in [0, 1].
        if max(float(np.max(xs)), float(np.max(ys))) <= 1.5:
            xs = xs * width
            ys = ys * height

        x0 = float(np.min(xs))
        y0 = float(np.min(ys))
        x1 = float(np.max(xs))
        y1 = float(np.max(ys))
        return fitz.Rect(x0, y0, x1, y1)

    def _run_predictor(self, img: np.ndarray) -> tuple[list[tuple[fitz.Rect, str, float]], float]:
        """ Regresa una lista de tuplas (rectángulo, texto, puntuación) para cada palabra detectada en la imagen, junto con el tiempo que tomó ejecutar el predictor.
        """
        # A degenerate image (0-width/0-height) makes onnxtr's resize divide by
        # zero (h / w). Skip inference and return no words.
        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return [], 0.0

        start = perf_counter()
        document = self.predictor([img])
        elapsed = perf_counter() - start

        page = document.pages[0]
        h, w = img.shape[:2]
        words: list[tuple[fitz.Rect, str, float]] = []

        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    text = str(getattr(word, "value", "")).strip()
                    if not text:
                        continue
                    rect = self._geometry_to_pixel_rect(getattr(word, "geometry", None), w, h)
                    if rect is None:
                        continue
                    conf = getattr(word, "confidence", 1.0)
                    score = float(conf) if conf is not None else 1.0
                    words.append((rect, text, score))

        # page holds a reference into document — release both before returning
        # so onnxtr's internal tensors and feature maps can be freed by the GC.
        del page, document
        return words, elapsed

    def render_orientation_probe(self, doc: fitz.Document, page_num: int) -> np.ndarray:
        """Rasteriza la página para sondear su orientación (fase BAJO lock)."""
        page = doc[page_num]
        longest = max(page.rect.width, page.rect.height)
        scale = min(1.5, 1400.0 / max(1.0, longest))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        base = self._pixmap_to_ndarray(pix)
        del pix
        return base

    def probe_orientation(
        self, doc: fitz.Document, page_num: int
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
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        img = self._pixmap_to_ndarray(pix)
        del pix
        native_angle: int | None = None
        if not self.page_needs_ocr(page):
            native_angle = self.detect_orientation_native(page)
        return img, native_angle

    def detect_orientation(self, doc: fitz.Document, page_num: int) -> int:
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
        ``/Rotate`` (PyMuPDF informa rotation==0 y la página se ve de lado).
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
        self, doc: fitz.Document, page_nums: list[int]
    ) -> list[np.ndarray]:
        """Rasteriza varias páginas para el sondeo multi-página (fase BAJO lock)."""
        images: list[np.ndarray] = []
        for pn in page_nums:
            page = doc[pn]
            longest = max(page.rect.width, page.rect.height)
            scale = min(1.5, 1400.0 / max(1.0, longest))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            images.append(self._pixmap_to_ndarray(pix))
            del pix
        return images

    def probe_pages_for_orientation(
        self, doc: fitz.Document, page_nums: list[int]
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
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            img = self._pixmap_to_ndarray(pix)
            del pix
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

    def get_doc_kind(self, doc: fitz.Document) -> str:
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
            has_text = bool(page.get_text("text").strip())
            has_images = bool(page.get_images(full=True))
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

    def page_kind(self, page: fitz.Page) -> str:
        """"
        Clasificar la página como 'nativa', 'escaneada' o 'híbrida' según su contenido.
         - 'nativa' si tiene texto extraíble pero no imágenes.
         - 'escaneada' si tiene imágenes pero no texto extraíble.
         - 'híbrida' si tiene tanto texto extraíble como imágenes.
         - Si no tiene texto ni imágenes, se clasifica como 'escaneada' por defecto.
        """
        has_text = bool(page.get_text("text").strip())
        has_images = bool(page.get_images(full=True))
        if has_text and not has_images:
            return "native"
        if has_images and not has_text:
            return "scanned"
        if has_images and has_text:
            return "hybrid"
        return "scanned" if not has_text else "native"

    def page_needs_ocr(self, page: fitz.Page) -> bool:
        """Return True only when the page lacks extractable native text."""
        return not bool(page.get_text("text").strip())

    def _native_segments(self, page: fitz.Page) -> list[OCRSegment]:
        segments: list[OCRSegment] = []
        for block in page.get_text("blocks"):
            if len(block) < 7:
                continue
            x0, y0, x1, y1, text, _, block_type = block[:7]
            if block_type != 0:
                continue
            clean = str(text).strip()
            if not clean:
                continue
            segments.append(
                OCRSegment(
                    text=clean,
                    source="native",
                    bbox=fitz.Rect(float(x0), float(y0), float(x1), float(y1)),
                )
            )
        return segments

    def _image_regions(self, page: fitz.Page) -> list[fitz.Rect]:
        regions: list[fitz.Rect] = []
        # get_image_info() only returns image metadata (bbox, size, …) without
        # loading all text content like get_text("dict") would.
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if not bbox:
                continue
            # get_image_info() devuelve el bbox en el espacio SIN rotar de la
            # página, pero get_pixmap(clip=...) y page.rect viven en el espacio
            # rotado (el que se muestra). En páginas con /Rotate 90/270 (típico
            # en escaneos) intersectar directamente recorta a un cuadrado y deja
            # fuera parte de la página. rotation_matrix mapea sin-rotar → rotado
            # (identidad si rotation == 0).
            # Clip to the page so bboxes that fall (partly) outside it don't
            # produce a degenerate pixmap later.
            rect = (fitz.Rect(bbox) * page.rotation_matrix) & page.rect
            if rect.is_empty or rect.width < 8 or rect.height < 8:
                continue
            regions.append(rect)

        # Some scanned PDFs have no image blocks; OCR the whole page as fallback.
        if not regions:
            regions.append(page.rect)
        return regions

    @staticmethod
    def _pixmap_to_ndarray(pix: fitz.Pixmap) -> np.ndarray:
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        return (arr[:, :, :3] if pix.n >= 3 else arr).copy()

    @staticmethod
    def _ocr_scale(rect: fitz.Rect) -> float:
        longest = max(rect.width, rect.height)
        scale = _SCALE_FOR_OCR
        if longest * scale > _MAX_OCR_PX:
            scale = _MAX_OCR_PX / longest
        return max(scale, 1.0)

    def prepare_page(self, doc: fitz.Document, page_num: int, force_ocr: bool = False) -> PreparedPage:
        """Fase 1 (BAJO el lock del documento): clasificar la página, extraer el
        texto nativo y rasterizar las regiones a OCRear. Es rápida (decenas de
        ms); todo lo que toca ``doc`` ocurre aquí."""
        page = doc[page_num]  # número de página 0-indexed en PyMuPDF
        doc_kind = self.get_doc_kind(doc)
        page_kind = self.page_kind(page)

        start = perf_counter()
        native_segments = self._native_segments(page)
        regions: list[tuple[fitz.Rect, float, np.ndarray]] = []
        if force_ocr or page_kind in ("hybrid", "scanned"):
            for rect in self._image_regions(page):
                scale = self._ocr_scale(rect)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    clip=rect,
                    alpha=False,
                )
                if pix.width == 0 or pix.height == 0:
                    del pix  # nothing to OCR in this region
                    continue
                img = self._pixmap_to_ndarray(pix)
                del pix  # free pixmap memory before inference
                regions.append((rect, scale, img))

        return PreparedPage(
            page_kind=page_kind,
            doc_kind=doc_kind,
            native_segments=native_segments,
            regions=regions,
            start=start,
        )

    def recognize_page(self, prep: PreparedPage) -> OCRPageResult:
        """Fase 2 (SIN lock): inferencia del modelo sobre las imágenes ya
        rasterizadas — los segundos lentos del OCR. No toca el documento."""
        ocr_segments: list[OCRSegment] = []
        detections: list[OCRDetection] = []
        ocr_elapsed = 0.0

        for rect, scale, img in prep.regions:
            words, elapsed = self._run_predictor(img)
            ocr_elapsed += elapsed
            for px_rect, text, score in words:
                x0 = rect.x0 + px_rect.x0 / scale
                y0 = rect.y0 + px_rect.y0 / scale
                x1 = rect.x0 + px_rect.x1 / scale
                y1 = rect.y0 + px_rect.y1 / scale
                pdf_rect = fitz.Rect(x0, y0, x1, y1)

                ocr_segments.append(OCRSegment(text=text, source="ocr", bbox=pdf_rect))
                detections.append(OCRDetection(text=text, score=score, source="ocr", bbox=pdf_rect))
        prep.regions.clear()  # liberar las imágenes rasterizadas cuanto antes

        segments = [*prep.native_segments, *ocr_segments]
        segments.sort(key=lambda s: (s.bbox.y0, s.bbox.x0))

        # Tipo de página: Nativo, Escaneado o Híbrido
        if prep.native_segments and ocr_segments:
            mode = "Hibrido"
        elif prep.native_segments:
            mode = "Nativo"
        elif ocr_segments:
            mode = "OCR"
        else:
            mode = "Sin texto"

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

    def process_page(self, doc: fitz.Document, page_num: int, force_ocr: bool = False) -> OCRPageResult:
        """Conveniencia (todo en uno) para llamadores sin lock que liberar —
        p. ej. el extractor por lotes. El visor usa las dos fases por separado
        para no retener su ``_doc_lock`` durante la inferencia."""
        return self.recognize_page(self.prepare_page(doc, page_num, force_ocr))
