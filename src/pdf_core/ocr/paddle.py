"""Modelos de PaddleOCR (PP-OCRv6 y PP-LCNet) con onnxruntime y NumPy.

Sustituye a onnxtr, que arrastraba OpenCV y SciPy (unos 200 MB en el ejecutable)
para el pre y posprocesado. Aquí ese trabajo se hace con NumPy, siguiendo la
configuración de cada modelo (``inference.yml`` de su repositorio):

- **Detección** (``PP-OCRv6_small_det``, DB): mapa de probabilidad de texto →
  cajas de LÍNEA (componentes conexas del mapa umbralizado, ampliadas).
- **Reconocimiento** (``PP-OCRv6_small_rec``, CTC): lee cada línea; las cajas de
  PALABRA salen de la posición de cada carácter en la salida CTC.
- **Orientación** (``PP-LCNet_x1_0_doc_ori``): clasifica la página en 0/90/180/270°.

Los modelos están en ``src/assets/ocr_models`` (ver su README). Para equipos con
pocos recursos se puede usar el reconocedor *tiny* cambiando :data:`REC_MODEL`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODELS_DIR = Path(__file__).resolve().parents[2] / "assets" / "ocr_models"
DET_MODEL = "PP-OCRv6_small_det"
REC_MODEL = "PP-OCRv6_small_rec"  # más rápido y algo menos preciso: "PP-OCRv6_tiny_rec"
ORI_MODEL = "PP-LCNet_x1_0_doc_ori"

_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)

# Detección (PostProcess de PP-OCRv6_small_det)
_DET_THRESH = 0.2       # probabilidad mínima de un píxel de texto
_DET_BOX_THRESH = 0.45  # probabilidad media mínima de una caja
_DET_UNCLIP = 1.4       # ampliación de la caja (el modelo predice el núcleo del texto)
_DET_MIN_SIZE = 3
_DET_MAX_SIDE = 4000
_DET_MIN_SIDE = 64

# Reconocimiento (RecResizeImg de PP-OCRv6_small_rec)
_REC_HEIGHT = 48
_REC_MIN_WIDTH = 320
_REC_MAX_WIDTH = 3200
_REC_BATCH = 8

_ORI_ANGLES = (0, 90, 180, 270)  # giro que TIENE la página, por clase


@dataclass
class Word:
    """Palabra reconocida, en píxeles de la imagen de entrada."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    score: float


def _session(name: str, models_dir: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3  # los modelos exportados avisan de inicializadores sin usar
    return ort.InferenceSession(str(models_dir / f"{name}.onnx"), options, providers=["CPUExecutionProvider"])


def resize(img: np.ndarray, width: int, height: int) -> np.ndarray:
    """Redimensionado bilineal (como ``cv2.resize`` con ``INTER_LINEAR``, el del entrenamiento)."""
    h, w = img.shape[:2]
    if (w, h) == (width, height):
        return img.astype(np.float32)
    ys = np.clip((np.arange(height, dtype=np.float32) + 0.5) * (h / height) - 0.5, 0, h - 1)
    xs = np.clip((np.arange(width, dtype=np.float32) + 0.5) * (w / width) - 0.5, 0, w - 1)
    y0 = ys.astype(np.int32)
    x0 = xs.astype(np.int32)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    fy = (ys - y0).astype(np.float32)[:, None, None]
    fx = (xs - x0).astype(np.float32)[None, :, None]
    # Separable: primero las filas y después las columnas (la mitad de trabajo).
    rows = img[y0] * (1 - fy) + img[y1] * fy
    return rows[:, x0] * (1 - fx) + rows[:, x1] * fx


def _normalize(img: np.ndarray) -> np.ndarray:
    """HWC 0–255 → CHW normalizado como ImageNet (detección y orientación)."""
    return ((img / 255.0 - _MEAN) / _STD).transpose(2, 0, 1).astype(np.float32)


def connected_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Rectángulos ``(x0, y0, x1, y1)`` (fin exclusivo) de las componentes conexas
    (8 vecinos) de ``mask``. Une los tramos de cada fila con los de la anterior
    (union-find): rápido porque el texto deja pocos tramos por fila."""
    runs: list[tuple[int, int, int]] = []  # (fila, inicio, fin)
    rows: list[tuple[int, int]] = []       # tramos de cada fila: runs[a:b]
    padded = np.zeros(mask.shape[1] + 2, np.int8)
    for y, row in enumerate(mask):
        padded[1:-1] = row
        edges = np.diff(padded)
        first = len(runs)
        runs.extend((y, int(s), int(e)) for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True))
        rows.append((first, len(runs)))

    parent = list(range(len(runs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for (a, a_end), (b, b_end) in zip(rows, rows[1:], strict=False):  # cada fila con la siguiente
        while a < a_end and b < b_end:
            _, s1, e1 = runs[a]
            _, s2, e2 = runs[b]
            if s1 <= e2 and s2 <= e1:  # se solapan o se tocan en diagonal
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
            if e1 < e2:
                a += 1
            else:
                b += 1

    boxes: dict[int, list[int]] = {}
    for i, (y, s, e) in enumerate(runs):
        box = boxes.setdefault(find(i), [s, y, e, y + 1])
        box[0] = min(box[0], s)
        box[2] = max(box[2], e)
        box[3] = y + 1
    return [tuple(b) for b in boxes.values()]


class TextRecognizer:
    """Detección + reconocimiento: ``recognizer(img)`` → palabras con su caja."""

    def __init__(self, models_dir: Path = MODELS_DIR, rec_model: str = REC_MODEL) -> None:
        self._det = _session(DET_MODEL, models_dir)
        self._rec = _session(rec_model, models_dir)
        chars = (models_dir / f"{rec_model}_dict.txt").read_text(encoding="utf-8").split("\n")[:-1]
        self._chars = ["", *chars, " "]  # 0 = separador CTC; el último, el espacio

    def __call__(self, img: np.ndarray) -> list[Word]:
        """``img``: RGB ``uint8`` (alto, ancho, 3)."""
        bgr = img[:, :, ::-1]  # los modelos se entrenaron con imágenes BGR
        lines = self.detect(bgr)
        return [word for line, box in zip(self.recognize(bgr, lines), lines, strict=True) for word in self._words(line, box)]

    # ── Detección ────────────────────────────────────────────────────────────
    def detect(self, bgr: np.ndarray) -> list[tuple[float, float, float, float]]:
        """Cajas de línea en píxeles, en orden de lectura aproximado."""
        h, w = bgr.shape[:2]
        ratio = 1.0
        if max(h, w) > _DET_MAX_SIDE:
            ratio = _DET_MAX_SIDE / max(h, w)
        elif min(h, w) < _DET_MIN_SIDE:
            ratio = _DET_MIN_SIDE / min(h, w)
        nh = max(32, round(h * ratio / 32) * 32)
        nw = max(32, round(w * ratio / 32) * 32)
        x = _normalize(resize(bgr, nw, nh))[None]
        prob = self._det.run(None, {"x": x})[0][0, 0]
        sx, sy = w / nw, h / nh
        boxes = []
        for x0, y0, x1, y1 in connected_boxes(prob > _DET_THRESH):
            bw, bh = x1 - x0, y1 - y0
            if min(bw, bh) < _DET_MIN_SIZE or prob[y0:y1, x0:x1].mean() < _DET_BOX_THRESH:
                continue
            d = bw * bh * _DET_UNCLIP / (2 * (bw + bh))  # ampliación de DB para un rectángulo
            if min(bw, bh) + 2 * d < _DET_MIN_SIZE + 2:
                continue
            boxes.append((max(0.0, (x0 - d) * sx), max(0.0, (y0 - d) * sy), min(w, (x1 + d) * sx), min(h, (y1 + d) * sy)))
        boxes.sort(key=lambda b: (b[1], b[0]))
        return boxes

    # ── Reconocimiento ───────────────────────────────────────────────────────
    def recognize(self, bgr: np.ndarray, boxes: list[tuple[float, float, float, float]]) -> list[tuple[np.ndarray, float]]:
        """Por cada caja: las probabilidades CTC (pasos × clases) y la fracción
        de la entrada que ocupa la línea (el resto es relleno)."""
        crops = []
        for x0, y0, x1, y1 in boxes:
            crop = bgr[int(y0) : int(np.ceil(y1)), int(x0) : int(np.ceil(x1))]
            width = min(_REC_MAX_WIDTH, max(1, int(np.ceil(_REC_HEIGHT * crop.shape[1] / max(1, crop.shape[0])))))
            crops.append((crop, width))
        results: list[tuple[np.ndarray, float]] = [None] * len(crops)  # type: ignore[list-item]
        order = sorted(range(len(crops)), key=lambda i: crops[i][1])  # lotes de anchura parecida
        for start in range(0, len(order), _REC_BATCH):
            batch = order[start : start + _REC_BATCH]
            width = max(_REC_MIN_WIDTH, *(crops[i][1] for i in batch))
            x = np.zeros((len(batch), 3, _REC_HEIGHT, width), np.float32)
            for n, i in enumerate(batch):
                crop, w = crops[i]
                x[n, :, :, :w] = (resize(crop, w, _REC_HEIGHT) / 127.5 - 1.0).transpose(2, 0, 1)
            probs = self._rec.run(None, {"x": x})[0]
            for n, i in enumerate(batch):
                results[i] = (probs[n], crops[i][1] / width)
        return results

    def _words(self, line: tuple[np.ndarray, float], box: tuple[float, float, float, float]) -> list[Word]:
        """Decodifica CTC y parte la línea en palabras: cada paso de la salida
        cubre una franja horizontal de la línea."""
        probs, used = line
        ids = probs.argmax(1)
        conf = probs.max(1)
        space = len(self._chars) - 1
        x0, y0, x1, y1 = box
        step = (x1 - x0) / (len(ids) * used)
        groups: list[list[int]] = []  # pasos de cada palabra
        current: list[int] = []
        prev = 0
        for t, c in enumerate(ids):
            if c != prev and c != 0:
                if c == space:
                    if current:
                        groups.append(current)
                    current = []
                else:
                    current.append(t)
            prev = c
        if current:
            groups.append(current)
        words = []
        for n, steps in enumerate(groups):
            left = x0 if n == 0 else x0 + max(0.0, steps[0] - 0.5) * step
            right = x1 if n == len(groups) - 1 else min(x1, x0 + (steps[-1] + 1.5) * step)
            text = "".join(self._chars[ids[t]] for t in steps)
            words.append(Word(left, y0, right, y1, text, float(np.mean(conf[steps]))))
        return words


class OrientationClassifier:
    """``classifier(img)`` → ``(grados a SUMAR a la rotación para enderezarla, confianza)``."""

    def __init__(self, models_dir: Path = MODELS_DIR) -> None:
        self._session = _session(ORI_MODEL, models_dir)

    def __call__(self, img: np.ndarray) -> tuple[int, float]:
        """``img``: RGB ``uint8``. Como en el entrenamiento: lado corto a 256 y recorte central de 224."""
        bgr = img[:, :, ::-1]
        h, w = bgr.shape[:2]
        scale = 256 / min(h, w)
        nw, nh = max(224, round(w * scale)), max(224, round(h * scale))
        left, top = (nw - 224) // 2, (nh - 224) // 2
        x = _normalize(resize(bgr, nw, nh)[top : top + 224, left : left + 224])[None]
        probs = self._session.run(None, {"x": x})[0][0]  # ya son probabilidades
        best = int(probs.argmax())
        return (360 - _ORI_ANGLES[best]) % 360, float(probs[best])
