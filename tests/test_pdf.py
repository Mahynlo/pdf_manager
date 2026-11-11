"""Capa de PDFium (``pdf_core.pdf``), texto y lo que no puede fallar al censurar."""
from __future__ import annotations

import base64
import json
import re
import threading
import zlib

import numpy as np
import pytest
from pdfkit import add_annot, add_image, add_page, add_text, annot_names, annots, encrypted, pdf_bytes, run_engine

from pdf_core import redaction
from pdf_core.pdf import UNRESTRICTED, Document, PageText, PasswordError, PdfError, Rect, png, unpack_page_texts
from pdf_core.reading_order import sort_words_clustered, sort_words_column_aware
from pdf_core.text_layer import build_text_layer, page_words

ROTATIONS = [0, 90, 180, 270]


def _doc(rotation: int = 0) -> Document:
    doc = Document.new()
    page = add_page(doc, 400, 600)
    add_text(page, 50, 100, "Hola mundo", 14)
    add_text(page, 50, 200, "Segunda linea", 12)
    if rotation:
        page.set_rotation(rotation)
    return doc


# ── Rect ─────────────────────────────────────────────────────────────────────
def test_rect():
    rect = Rect(10, 20, 30, 60)
    assert (rect.width, rect.height, rect.area) == (20, 40, 800)
    assert rect & (0, 0, 15, 30) == Rect(10, 20, 15, 30)
    assert rect.intersects((29, 59, 40, 70)) and not rect.intersects((30, 60, 40, 70))
    assert Rect(5, 5, 5, 9).is_empty and Rect(5, 5, 5, 9).area == 0


# ── Abrir ────────────────────────────────────────────────────────────────────
def test_open_errors(tmp_path):
    with pytest.raises(PdfError):
        Document.open(b"esto no es un PDF")
    with pytest.raises(OSError):
        Document.open(tmp_path / "falta.pdf")
    data = encrypted(pdf_bytes([[(72, 72, "secreto")]]), "clave")
    with pytest.raises(PasswordError):
        Document.open(data)
    with pytest.raises(PasswordError):
        Document.open(data, "mal")
    with Document.open(data, "clave") as doc:
        assert doc.encrypted and doc[0].text().strip() == "secreto"


def test_open_does_not_lock_the_file(tmp_path):
    path = tmp_path / "abierto.pdf"
    path.write_bytes(pdf_bytes([[(72, 72, "uno")]]))
    with Document.open(path) as doc:
        path.write_bytes(pdf_bytes([[(72, 72, "dos")]]))  # en Windows, fallaría si estuviera abierto
        assert doc[0].text().strip() == "uno"


def test_saving_keeps_or_removes_the_encryption():
    data = encrypted(pdf_bytes([[(72, 72, "texto")]]), "user", "owner", 4)
    with Document.open(data, "user") as doc:
        assert doc.permissions == 4
        doc[0].set_rotation(90)
        with pytest.raises(PasswordError):
            Document.open(doc.to_bytes())
        with Document.open(doc.to_bytes(), "user") as again:
            assert again[0].rotation == 90 and again.encrypted
        with Document.open(doc.to_bytes(decrypt=True)) as free:
            assert not free.encrypted and free.permissions == UNRESTRICTED
    with Document.open(data, "owner") as doc:
        assert doc.permissions == UNRESTRICTED


# ── Coordenadas y texto ──────────────────────────────────────────────────────
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_view_coordinates(rotation):
    with _doc(rotation) as doc:
        page = doc[0]
        assert page.rotation == rotation
        assert tuple(page.rect) == ((0, 0, 600, 400) if rotation in (90, 270) else (0, 0, 400, 600))
        assert page.to_page(page.to_view((10, 20, 30, 50))) == (10, 20, 30, 50)
        word = page.words()[0][0]  # «Hola», cerca de (50, 100) en la página sin girar
        assert 45 < word.x0 < 55 and 80 < word.y0 < 105
        assert page.words()[0][1] == "Hola"
        view = page.to_view(word)
        assert view.width > view.height if rotation in (0, 180) else view.height > view.width


def test_crop_box_moves_the_origin():
    with _doc() as doc:
        data = doc.to_bytes()
    with Document.open(data) as doc:
        with doc[0]._opened() as page:
            page.set_cropbox(40, 0, 400, 550)  # quita 40 pt a la izquierda y 50 arriba
        doc._meta.clear()
        page = doc[0]
        assert tuple(page.rect) == (0, 0, 360, 550)
        word = page.words()[0][0]
        assert 5 < word.x0 < 15 and 30 < word.y0 < 55


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_text_and_words_follow_the_lines(rotation):
    with _doc(rotation) as doc:
        page = doc[0]
        assert page.text().split("\n") == ["Hola mundo", "Segunda linea"]
        with Document.open(doc.to_bytes()) as saved:  # leer el texto no cambia el giro guardado
            assert saved[0].rotation == rotation
        assert [(text, line) for _rect, text, line in page.words()] == [("Hola", 0), ("mundo", 0), ("Segunda", 1), ("linea", 1)]


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_text_direction_follows_the_rotation(rotation):
    wx, wy = _doc(rotation)[0].text_direction()
    expected = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[rotation]
    assert (round(wx / max(abs(wx), abs(wy))), round(wy / max(abs(wx), abs(wy)))) == expected


def test_render_and_clip():
    with Document.new() as doc:
        page = add_page(doc, 200, 100)
        add_image(page, Rect(0, 0, 100, 100), np.full((10, 10, 3), (255, 0, 0), np.uint8))
        assert page.render(1).shape == (100, 200, 3)
        assert page.render(2).shape == (200, 400, 3)
        assert page.render(1, rotation=90).shape == (200, 100, 3)
        red = page.render(1, clip=(10, 10, 60, 50))
        assert red.shape == (40, 50, 3) and red[20, 25].tolist() == [255, 0, 0]  # RGB, no BGR
        assert page.render(1, clip=(120, 10, 180, 50))[20, 25].tolist() == [255, 255, 255]


def test_images_are_found_inside_their_rectangle():
    with Document.new() as doc:
        page = add_page(doc, 400, 600)
        add_image(page, Rect(50, 300, 130, 360), np.full((6, 8, 3), 90, np.uint8))
        assert page.has_images()
        assert [tuple(round(v) for v in r) for r in page.image_rects()] == [(50, 300, 130, 360)]
        page.set_rotation(90)
        assert [tuple(round(v) for v in r) for r in page.image_rects()] == [(240, 50, 300, 130)]
        (ext, data), = page.export_images()
        assert ext == "png" and data.startswith(b"\x89PNG")


def test_png():
    data = png(np.full((3, 4, 3), 7, np.uint8))
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and b"IHDR" in data and data.endswith(b"IEND\xaeB`\x82")
    start = data.index(b"IDAT") + 4
    raw = zlib.decompressobj().decompress(data[start:])
    assert raw == (b"\0" + b"\x07" * 12) * 3


# ── Páginas ──────────────────────────────────────────────────────────────────
def test_page_operations_keep_identity_and_annotations():
    with Document.open(pdf_bytes([[(72, 72, f"pagina {i}")] for i in range(3)])) as doc:
        add_annot(doc[1], "Square", Rect(10, 10, 50, 50))
        first, second, third = doc.uids

        doc.move_page(0, 2)
        assert doc.uids == [second, third, first]
        assert [p.text().strip() for p in doc] == ["pagina 1", "pagina 2", "pagina 0"]
        doc.move_page(2, 0)

        doc.insert_pages(doc, [1], 2)
        assert annots(doc[2]) == ["Square"] and doc[2].text().strip() == "pagina 1"
        assert doc.uids[1] == second and doc.uids[2] not in (first, second, third)
        doc.delete_page(2)

        doc.new_page(1, doc[0].rect.width, doc[0].rect.height)
        assert tuple(doc[1].rect) == tuple(doc[0].rect) and doc[1].text() == ""
        doc.delete_page(1)

        with Document.new() as copy:
            copy.insert_pages(doc, [1], uids=[second])
            doc.delete_page(1)
            doc.insert_pages(copy, [0], 1, uids=copy.uids)
        assert doc.uids == [first, second, third] and annots(doc[1]) == ["Square"]

        with Document.open(doc.to_bytes()) as saved:
            assert [p.text().strip() for p in saved] == ["pagina 0", "pagina 1", "pagina 2"]
            saved.adopt_uids(doc)
            assert saved.uids == doc.uids


# ── Páginas en el motor del visor (lib/pdf-engine/native.ts) ─────────────────
def _engine_pages(data: bytes, ops: list[list], password: str | None = None) -> bytes:
    """Lo que hace el visor con las páginas (document/pages.ts), con el motor de EmbedPDF."""
    return run_engine("pages", data, {"ops": ops, "password": password})


def _three_pages(note_on: int) -> bytes:
    with Document.open(pdf_bytes([[(72, 72, f"pagina {i}")] for i in range(3)])) as doc:
        add_annot(doc[note_on], "Square", Rect(10, 10, 50, 50), name="nota")
        return doc.to_bytes()


def test_engine_changes_pages_with_their_annotations():
    ops = [
        ["rotate", [0], 1],  # [0↻, 1, 2]
        ["blank", 1, 300, 200],  # [0↻, B, 1, 2]
        ["duplicate", 2, 3],  # [0↻, B, 1, 1', 2]
        ["move", 4, 0],  # [2, 0↻, B, 1, 1']
        ["remove", 4],  # [2, 0↻, B, 1]
    ]
    with Document.open(_engine_pages(_three_pages(note_on=1), ops)) as doc:
        assert [p.text().strip() for p in doc] == ["pagina 2", "pagina 0", "", "pagina 1"]
        assert [p.rotation for p in doc] == [0, 90, 0, 0]  # el giro queda en el archivo
        assert [annots(p) for p in doc] == [[], [], [], ["Square"]]  # cada anotación va con su página
        assert (doc[2].rect.width, doc[2].rect.height) == (300, 200)


def test_engine_turns_pages_that_were_already_turned():
    with Document.open(pdf_bytes([[(72, 72, "girada")]])) as doc:
        doc[0].set_rotation(90)
        data = doc.to_bytes()
    with Document.open(_engine_pages(data, [["rotate", [0], -1]])) as doc:
        assert doc[0].rotation == 0
    with Document.open(_engine_pages(data, [["rotate", [0], 2]])) as doc:
        assert doc[0].rotation == 270


def test_engine_gives_the_copy_of_a_page_new_annotation_ids():
    with Document.open(_engine_pages(_three_pages(note_on=0), [["duplicate", 0, 1]])) as doc:
        original, (copy,) = annot_names(doc[0]), annot_names(doc[1])
        assert original == ["nota"] and copy and copy != "nota"  # EmbedPDF las distingue por /NM


def test_engine_gives_back_a_removed_page_with_its_annotations():
    with Document.open(_engine_pages(_three_pages(note_on=1), [["remove-restore", 1]])) as doc:
        assert [p.text().strip() for p in doc] == ["pagina 0", "pagina 1", "pagina 2"]
        assert annot_names(doc[1]) == ["nota"]


def test_engine_page_changes_keep_the_encryption():
    data = encrypted(pdf_bytes([[(72, 72, "secreto")], [(72, 72, "otra")]]), "clave")
    done = _engine_pages(data, [["rotate", [1], -1]], password="clave")
    with pytest.raises(PasswordError):
        Document.open(done)
    with Document.open(done, "clave") as doc:
        assert doc.encrypted and [p.rotation for p in doc] == [0, 270]


# ── Copias en el motor del visor (guardar, imprimir, extraer: document/copy.ts) ─
def _with_ocr(data: bytes, pages: dict[int, list[list]], replace: bool = False, password: str | None = None) -> bytes:
    """Lo que hace el visor tras un OCR (canvas.writeOcrText): ``pages``, palabras
    ``[x0, y0, x1, y1, texto]`` (de vista) por página, escritas como texto invisible."""
    items = [{"index": index, "words": words, "replace": replace} for index, words in pages.items()]
    return run_engine("ocr-write", data, {"pages": items, "password": password})


def _recognized(password: str | None = None) -> bytes:
    """Dos páginas con texto nativo y el de un OCR como texto invisible; una nota en la primera."""
    with Document.open(pdf_bytes([[(72, 72, "uno")], [(72, 72, "dos")]])) as doc:
        add_annot(doc[0], "Square", Rect(10, 10, 50, 50), name="nota")
        data = doc.to_bytes()
    data = _with_ocr(data, {i: [[40, 240, 140, 260, "reconocido"]] for i in range(2)})
    return encrypted(data, password) if password else data


def test_engine_copy_leaves_out_the_ocr_text_of_the_given_pages():
    with Document.open(run_engine("copy", _recognized(), {"withoutText": [0]})) as doc:
        assert "reconocido" not in doc[0].text() and "uno" in doc[0].text()
        assert annot_names(doc[0]) == ["nota"]  # lo demás de la página sigue
        assert "reconocido" in doc[1].text()  # la otra página no se toca


def test_engine_copy_keeps_the_encryption_unless_it_is_for_printing():
    data = _recognized("clave")
    kept = run_engine("copy", data, {"withoutText": [0, 1], "password": "clave"})
    with pytest.raises(PasswordError):
        Document.open(kept)
    with Document.open(kept, "clave") as doc:
        assert doc.encrypted and all("reconocido" not in p.text() for p in doc)
    with Document.open(run_engine("copy", data, {"decrypt": True, "password": "clave"})) as doc:
        assert not doc.encrypted and [p.text().count("uno") for p in doc] == [1, 0]


def test_engine_extracts_pages_without_ocr_text_or_encryption():
    out = run_engine("extract", _recognized("clave"), {"indices": [1, 0], "withoutText": [0], "password": "clave"})
    with Document.open(out) as doc:
        assert not doc.encrypted
        assert "dos" in doc[0].text() and "reconocido" in doc[0].text()
        assert "uno" in doc[1].text() and "reconocido" not in doc[1].text()
        assert annot_names(doc[1]) == ["nota"]


def test_engine_tells_the_pdf_version_and_encryption():
    assert json.loads(run_engine("facts", _recognized("clave"), {"password": "clave"})) == {"version": "1.7", "encrypted": True}
    assert json.loads(run_engine("facts", _recognized(), {}))["encrypted"] is False


def test_threads_do_not_crash_the_engine():
    """PDFium no admite hilos: todo pasa por un candado, también con documentos distintos."""
    data = pdf_bytes([[(72, 72, f"pagina {i}")] for i in range(20)])
    errors: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(3):
                with Document.open(data) as doc:
                    for page in doc:
                        assert page.text().startswith("pagina")
                        page.render(0.2)
        except BaseException as ex:  # noqa: BLE001 - se comprueba abajo
            errors.append(ex)

    threads = [threading.Thread(target=work) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors


# ── El OCR en el motor del visor (lib/pdf-engine/page-ocr.ts) ────────────────
@pytest.mark.parametrize("rotation", ROTATIONS)
def test_engine_writes_ocr_words_on_their_rectangle(rotation):
    with _doc(rotation) as doc:
        data = doc.to_bytes()
        before = doc[0].render(1)
    with Document.open(_with_ocr(data, {0: [[40, 240, 140, 260, "cañón"]]})) as doc:
        page = doc[0]
        ((rect, text),) = [(r, t) for r, t, _line in page.words() if "ca" in t]
        assert text == "cañón"
        got = page.to_view(rect)
        assert abs(got.x0 - 40) < 5 and abs(got.x1 - 140) < 5 and abs(got.y0 - 240) < 8
        assert np.array_equal(page.render(1), before)  # es invisible: la página se ve igual


def test_engine_ocr_words_replace_the_previous_ones_and_skip_native_text():
    with _doc() as doc:
        native = doc[0].to_view(doc[0].words()[0][0])
        data = doc.to_bytes()
    first = _with_ocr(data, {0: [[40, 300, 100, 320, "Primera"]]})
    words = [[*native, "Repetido"], [40, 400, 100, 420, "Nueva"], [10, 10, 10, 10, "vacia"]]
    with Document.open(_with_ocr(first, {0: words}, replace=True)) as doc:
        text = doc[0].text()
        assert "Nueva" in text and "Hola mundo" in text  # el texto nativo no se toca
        assert "Primera" not in text and "Repetido" not in text and "vacia" not in text
    with Document.open(_with_ocr(first, {0: [[40, 400, 100, 420, "Nueva"]]})) as doc:
        assert "Primera" in doc[0].text() and "Nueva" in doc[0].text()  # un recorte se suma


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_engine_reads_page_facts_without_the_ocr_text(rotation):
    with _doc() as doc:
        add_image(doc[0], Rect(100, 300, 300, 400), np.full((20, 40, 3), 128, np.uint8))
        if rotation:
            doc[0].set_rotation(rotation)
        images = doc[0].image_rects()
        data = _with_ocr(doc.to_bytes(), {0: [[40, 500, 140, 520, "reconocido"]]})
    facts = json.loads(run_engine("ocr-facts", data, {"index": 0}))
    assert facts["chars"] == len("Holamundo" "Segundalinea") and facts["lines"] == 2
    assert [pytest.approx(list(r), abs=0.5) for r in images] == facts["images"]
    wx, wy = facts["direction"]  # el texto se ve girado como la página
    want = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[rotation]
    assert (round(wx / facts["chars"]), round(wy / facts["chars"])) == want


@pytest.mark.parametrize("rotation", [0, 90])
def test_engine_draws_the_page_as_seen_for_the_ocr(rotation):
    with _doc(rotation) as doc:
        clip = Rect(20, 60, 220, 240)
        want = doc[0].render(2, clip=clip)
        whole = doc[0].render(0.5)
        data = doc.to_bytes()
    image = json.loads(run_engine("ocr-image", data, {"index": 0, "scale": 2, "clip": list(clip)}))
    got = np.frombuffer(base64.b64decode(image["data"]), np.uint8).reshape(image["height"], image["width"], 3)
    assert got.shape == want.shape
    assert np.abs(got.astype(int) - want).mean() < 3  # el mismo PDFium, otra compilación
    image = json.loads(run_engine("ocr-image", data, {"index": 0, "scale": 0.5}))
    assert (image["height"], image["width"]) == whole.shape[:2]


def _engine_texts(data: bytes, indices: list[int], password: str | None = None) -> list[tuple[int, PageText]]:
    """El texto que da el motor del visor a Python (lib/pdf-engine/page-text.ts)."""
    out = json.loads(run_engine("texts", data, {"indices": indices, "password": password}))
    return [(index, packed.unpack()) for index, packed in unpack_page_texts(out["pages"], base64.b64decode(out["data"]))]


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_engine_gives_python_the_same_page_text_without_the_ocr(rotation):
    with _doc(rotation) as doc:
        want = doc[0].page_text()
        data = _with_ocr(doc.to_bytes(), {0: [[40, 500, 140, 520, "reconocido"]]})
    ((index, got),) = _engine_texts(data, [0])
    assert index == 0 and got.geometry == pytest.approx(want.geometry)
    assert got.text() == want.text() == "Hola mundo\nSegunda linea"  # sin el texto del OCR
    assert [c.line for c in got.chars] == [c.line for c in want.chars]
    for mine, theirs in zip(got.chars, want.chars, strict=True):  # otra compilación de PDFium: ±0,6 pt
        assert list(mine.box) == pytest.approx(list(theirs.box), abs=1)
    assert build_text_layer(got).text == build_text_layer(want).text


def test_engine_page_texts_come_in_the_order_asked():
    data = pdf_bytes([[(72, 72, f"pagina {i}")] for i in range(3)])
    texts = _engine_texts(data, [2, 0])
    assert [(i, t.text().strip()) for i, t in texts] == [(2, "pagina 2"), (0, "pagina 0")]
    with pytest.raises(PdfError):
        unpack_page_texts([{"index": 0, "geometry": [1, 1, 0, 1, 0], "count": 3}], bytes(10))


# ── Capa de texto y orden de lectura ─────────────────────────────────────────
def test_text_layer_has_spaces_and_lines():
    with _doc() as doc:
        layer = build_text_layer(doc[0].page_text())
        assert layer.text == "Hola mundo\nSegunda linea"
        assert len(layer.chars) == len(layer.rects) == len(layer.seps)


def test_text_layer_keeps_tall_and_short_letters_together():
    """Las cajas de glifo de «C» y de «o» no están a la misma altura; las líneas no se parten por eso."""
    with Document.new() as doc:
        page = add_page(doc)
        add_text(page, 72, 100, "Contrato con Juan Pérez, gypsy", 12)
        assert build_text_layer(page.page_text()).text == "Contrato con Juan Pérez, gypsy"


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_text_layer_reads_rotated_pages(rotation):
    with _doc(rotation) as doc:
        assert build_text_layer(doc[0].page_text()).text == "Hola mundo\nSegunda linea"


def test_page_words_merges_ocr_with_native_text():
    with _doc() as doc:
        words = page_words(doc[0].page_text(), [(50, 300, 100, 320, "Tercera")])
        assert "Tercera" in [w[1] for w in words]


def _char(ch: str, x0: float, x1: float, start: bool = False) -> tuple:
    return (Rect(x0, 100, x1, 112), ch, start)


def test_overlapping_word_boxes_keep_stream_order():
    """Capa «buscable»: las cajas de palabras vecinas se solapan. Ordenar carácter a carácter
    por x0 entrelazaba las letras («GASTODSE»); con los grupos del contenido no pasa."""
    words = [
        _char("G", 0, 10), _char("A", 10, 20), _char("S", 20, 30), _char("T", 30, 40),
        _char("O", 40, 50), _char("S", 58, 68), _char("D", 52, 62, True), _char("E", 62, 72),
    ]
    out = sort_words_clustered(words, 595, groups=[1, 1, 1, 1, 1, 1, 2, 2])
    assert "".join(w[1] for w in out) == "GASTOSDE"


def test_column_aware_sorter_is_also_group_ordered():
    words = [_char("A", 0, 12), _char("B", 18, 30), _char("C", 26, 38, True), _char("D", 38, 50)]
    out = sort_words_column_aware(words, 595, groups=[1, 1, 2, 2])
    assert "".join(w[1] for w in out) == "ABCD"


# ── Buscar para censurar ─────────────────────────────────────────────────────
def _find(page, term, *, case_sensitive=False, whole_word=False, regex=False):
    return redaction.find_in_page(page.page_text(), term, case_sensitive=case_sensitive, whole_word=whole_word, regex=regex)


def test_find_ignores_accents_and_case_and_keeps_enye():
    with Document.open(pdf_bytes([[(72, 100, "Comité de Pérez"), (72, 120, "el año pasado")]])) as doc:
        page = doc[0]
        assert len(_find(page, "COMITE")) == 1 and len(_find(page, "perez")) == 1
        assert _find(page, "ano") == []  # año no es ano
        assert _find(page, "perez", case_sensitive=True) == [] and len(_find(page, "Perez", case_sensitive=True)) == 1


def test_find_whole_word_and_regex():
    with Document.open(pdf_bytes([[(72, 100, "pago pagos, pago."), (72, 120, "correo juan@correo.com")]])) as doc:
        page = doc[0]
        assert len(_find(page, "pago")) == 3
        assert len(_find(page, "pago", whole_word=True)) == 2
        assert len(_find(page, r"[\w.]+@[\w.]+", regex=True)) == 1
        assert _find(page, "[", regex=True) == []  # patrón a medio escribir


def test_find_phrase_split_in_two_lines_gives_one_rect_per_line():
    with Document.open(pdf_bytes([[(72, 100, "dice Juan"), (72, 120, "Pérez y otros")]])) as doc:
        first, second = _find(doc[0], "juan perez")
        assert first.y1 <= second.y0 + 4 and first.x0 > second.x0


def test_find_rect_covers_the_word():
    with Document.open(pdf_bytes([[(72, 100, "palabra")]])) as doc:
        (rect,) = _find(doc[0], "palabra")
        assert rect.y0 < 95 and rect.y1 > 100  # alto de la fuente: cubre tildes y descendentes


# ── Censurar: lo que hay debajo desaparece del archivo ───────────────────────
SECRET = "SECRETO-123"


def _streams(data: bytes) -> list[bytes]:
    """Todos los streams del archivo, descomprimidos; también los que nadie referencia."""
    found = []
    for match in re.finditer(rb"stream\r?\n", data):
        end = data.find(b"endstream", match.end())
        chunk = data[match.end():end]
        try:
            found.append(zlib.decompressobj().decompress(chunk))
        except zlib.error:
            found.append(chunk)
    return found


def _secret_pdf() -> bytes:
    with Document.new() as doc:
        page = add_page(doc, 600, 800)
        add_text(page, 72, 100, "Publico")
        add_text(page, 72, 140, SECRET)
        add_image(page, Rect(72, 200, 272, 300), _half_red())
        return doc.to_bytes()


def _half_red() -> np.ndarray:
    image = np.zeros((100, 200, 3), np.uint8)
    image[:, :100] = (255, 0, 0)
    image[:, 100:] = (0, 0, 255)
    return image


def _redacted(rects: list[list[float]], color: str = "#000000") -> bytes:
    marked = run_engine("mark", _secret_pdf(), {"marks": [{"page": 0, "rect": r, "color": color} for r in rects]})
    return run_engine("redact", marked, {})


def test_redaction_removes_the_text_from_the_file():
    data = _redacted([[70, 125, 300, 145]])
    with Document.open(data) as doc:
        assert SECRET not in doc[0].text() and "Publico" in doc[0].text()
        assert annots(doc[0]) == []  # la marca desaparece
    assert not any(SECRET.encode() in s or b"SECRETO" in s for s in [data, *_streams(data)])


def test_redaction_clears_the_pixels_under_the_mark():
    data = _redacted([[72, 200, 172, 300]])  # la mitad roja de la imagen
    with Document.open(data) as doc:
        # La imagen sigue, pero en ella ya no hay rojo: tampoco en ningún stream del archivo.
        image = doc[0].render(1, clip=(180, 210, 260, 290))
        assert image[40, 40].tolist() == [0, 0, 255]  # la mitad azul sigue ahí
    (pixels,) = [s for s in _streams(data) if len(s) == 100 * 200 * 3]  # la imagen, decodificada
    image = np.frombuffer(pixels, np.uint8).reshape(100, 200, 3)
    assert not ((image[..., 0] > 200) & (image[..., 2] < 50)).any()
    assert ((image[..., 2] > 200) & (image[..., 0] < 50)).sum() == 100 * 100  # la azul, intacta


def test_redaction_paints_the_chosen_color():
    data = _redacted([[70, 125, 300, 145]], "#B21A1A")
    with Document.open(data) as doc:
        r, g, b = doc[0].render(1, clip=(100, 130, 200, 140))[5, 50]
        assert r > 150 and g < 60 and b < 60


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_redaction_on_rotated_pages(rotation):
    """Las marcas van en coordenadas de la página sin girar, como en el visor."""
    with Document.open(_secret_pdf()) as doc:
        doc[0].set_rotation(rotation)
        (rect,) = redaction.find_in_page(doc[0].page_text(), SECRET, case_sensitive=False, whole_word=False, regex=False)
        view = doc[0].to_view(rect)
        data = doc.to_bytes()
    marked = run_engine("mark", data, {"marks": [{"page": 0, "rect": list(rect), "color": "#B21A1A"}]})
    done = run_engine("redact", marked, {})
    with Document.open(done) as doc:
        page = doc[0]
        assert page.rotation == rotation and "SECRETO" not in page.text() and "Publico" in page.text()
        image = page.render(1, clip=view)
        r, g, b = image[image.shape[0] // 2, image.shape[1] // 2]
        assert r > 150 and g < 60 and b < 60  # el recuadro está donde estaba el texto


def test_redaction_keeps_the_encryption():
    data = encrypted(_secret_pdf(), "clave")
    marked = run_engine("mark", data, {"password": "clave", "marks": [{"page": 0, "rect": [70, 125, 300, 145], "color": "#000000"}]})
    done = run_engine("redact", marked, {"password": "clave"})
    with pytest.raises(PasswordError):
        Document.open(done)
    with Document.open(done, "clave") as doc:
        assert SECRET not in doc[0].text()
