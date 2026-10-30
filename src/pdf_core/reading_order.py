"""Ordenación de palabras en orden de lectura (columnas y líneas).

Independiente de la interfaz: la usan la capa de texto de ``text_layer`` (visor HTML)
y la selección de texto del visor Qt. Cada palabra es una tupla ``(fitz.Rect, texto,
inicio_de_palabra[, línea])``.
"""

from __future__ import annotations

from collections.abc import Callable


# ── COLUMN-AWARE & CLUSTERED READING ORDER FUNCTIONS ────────────────────────
def group_aware_order(n: int, line_key: Callable[[int], any], x0_of: Callable[[int], float], groups: list[int] | None) -> list[int]:
    if groups is None:
        return sorted(range(n), key=lambda i: (line_key(i), x0_of(i)))
    gx0: dict[tuple, float] = {}
    for i in range(n):
        k = (line_key(i), groups[i])
        x = x0_of(i)
        if k not in gx0 or x < gx0[k]:
            gx0[k] = x
    return sorted(
        range(n), key=lambda i: (line_key(i), gx0[(line_key(i), groups[i])], i)
    )


def sort_words_column_aware(
    words: list[tuple], page_width: float, pos=None, groups: list[int] | None = None
) -> list[tuple]:
    if pos is None:
        pos = lambda r: r
    prects = [pos(w[0]) for w in words]
    n = len(words)
    if n < 4:
        order = group_aware_order(
            n,
            lambda i: round(prects[i].y0 / 5) * 5,
            lambda i: prects[i].x0,
            groups,
        )
        return [words[i] for i in order]

    x_centers = sorted((r.x0 + r.x1) / 2.0 for r in prects)
    threshold = max(30.0, page_width * 0.08)
    splits = []
    for i in range(len(x_centers) - 1):
        gap = x_centers[i + 1] - x_centers[i]
        if gap > threshold:
            splits.append((x_centers[i] + x_centers[i + 1]) / 2.0)

    if not splits:
        order = group_aware_order(
            n,
            lambda i: round(prects[i].y0 / 5) * 5,
            lambda i: prects[i].x0,
            groups,
        )
    else:
        def get_col_index(x):
            for k, split_x in enumerate(splits):
                if x < split_x:
                    return k
            return len(splits)

        cols = [get_col_index((r.x0 + r.x1) / 2.0) for r in prects]
        order = group_aware_order(
            n,
            lambda i: (cols[i], round(prects[i].y0 / 5) * 5),
            lambda i: prects[i].x0,
            groups,
        )

    return [words[i] for i in order]


def _line_tol(rects: list) -> float:
    if not rects:
        return 5.0
    heights = sorted(max(0.0, r.y1 - r.y0) for r in rects)
    med = heights[len(heights) // 2]
    return max(3.0, med * 0.6)


def assign_line_indices(words: list[tuple], pos=None) -> list[tuple]:
    if pos is None:
        pos = lambda r: r
    if not words:
        return []
    prects = [pos(w[0]) for w in words]
    tol = _line_tol(prects)
    out: list[tuple] = []
    mean: float | None = None
    cnt = 0
    lid = -1
    for w, pr in zip(words, prects, strict=True):
        cy = (pr.y0 + pr.y1) / 2
        if mean is None or abs(cy - mean) > tol:
            lid += 1
            mean = cy
            cnt = 1
        else:
            cnt += 1
            mean += (cy - mean) / cnt
        out.append((*w[:3], lid))
    return out


def sort_words_clustered(
    words: list[tuple], page_width: float, pos=None, groups: list[int] | None = None
) -> list[tuple]:
    if pos is None:
        pos = lambda r: r
    n = len(words)
    if n == 0:
        return []
    prects = [pos(w[0]) for w in words]
    cy = [(r.y0 + r.y1) / 2 for r in prects]
    cx = [(r.x0 + r.x1) / 2 for r in prects]
    tol = _line_tol(prects)

    xs = sorted(cx)
    threshold = max(30.0, page_width * 0.08)
    splits = []
    for i in range(len(xs) - 1):
        if xs[i + 1] - xs[i] > threshold:
            splits.append((xs[i] + xs[i + 1]) / 2.0)

    def col_of(x: float) -> int:
        for k, sx in enumerate(splits):
            if x < sx:
                return k
        return len(splits)

    cols = [col_of(x) for x in cx]
    order0 = sorted(range(n), key=lambda i: (cols[i], cy[i], prects[i].x0))
    line_id = [0] * n
    cur_col: int | None = None
    mean: float | None = None
    cnt = 0
    lid = -1
    for i in order0:
        if cols[i] != cur_col or mean is None or abs(cy[i] - mean) > tol:
            lid += 1
            cur_col = cols[i]
            mean = cy[i]
            cnt = 1
        else:
            cnt += 1
            mean += (cy[i] - mean) / cnt
        line_id[i] = lid

    order = group_aware_order(
        n, lambda i: line_id[i], lambda i: prects[i].x0, groups
    )
    return [(*words[i][:3], line_id[i]) for i in order]
