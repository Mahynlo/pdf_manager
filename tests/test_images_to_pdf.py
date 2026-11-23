"""Imágenes en el visor: abrirlas («Abrir», arrastrarlas), el PDF que crea la ventana con ellas
(``lib/images/images.ts``), el documento nuevo sin archivo (``viewer.create``), insertar o rehacer
páginas con el motor (``pages.ts`` ``insertPdf`` / ``replaceWithPdf``) y exportar las páginas como
imágenes (``viewer.save_page_image``).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from pdfkit import page_texts, pdf_bytes, run_engine
from test_app_backend import FakeHost, FakeViewer, _make_pdf, _put

from app.backend.rpc import UserError
from app.backend.services.documents import IMAGE_SUFFIXES, DocumentService
from app.backend.services.viewer import ViewerService
from pdf_core import recent_files
from pdf_core.pdf import Document

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
UI = ROOT / "app" / "ui" / "src"
A4 = (595.28, 841.89)
OPTIONS = {"paper": "a4", "orientation": "auto", "margin": "none", "fit": "contain"}


def _images_pdf(images: list[dict]) -> bytes:
    """El PDF que crea el visor con unas imágenes JPG (``imagesPdf``, con el motor de Node)."""
    return run_engine("images", pdf_bytes([[]]), {"images": images})


def _image(name: str, width: int, height: int, rotation: int = 0, **options: str) -> dict:
    return {"file": str(FIXTURES / name), "width": width, "height": height, "rotation": rotation, "options": {**OPTIONS, **options}}


def _color(doc: Document, index: int, x: float, y: float) -> tuple[int, ...]:
    """Color del punto (``x``, ``y``: fracción del ancho y del alto, desde arriba) de la página."""
    image = doc[index].render(1.0)
    h, w = image.shape[:2]
    return tuple(int(c) for c in image[int(y * (h - 1)), int(x * (w - 1))][:3])


def _reddish(color: tuple[int, ...]) -> bool:
    r, g, b = color
    return r > 150 and g < 100 and b < 100


def _bluish(color: tuple[int, ...]) -> bool:
    r, g, b = color
    return b > 150 and r < 100 and g < 100


# ── Abrir imágenes ──────────────────────────────────────────────────────────
def test_open_sends_the_images_together_and_pdfs_one_by_one(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", 1)
    photo = tmp_path / "foto.JPG"
    scan = tmp_path / "escaneo.png"
    photo.write_bytes((FIXTURES / "foto_exif6.jpg").read_bytes())
    scan.write_bytes(b"\x89PNG fingido")
    host = FakeHost(picks=[str(photo), str(pdf), str(scan)])
    docs = DocumentService(host)

    assert docs.open_dialog() == [str(photo), str(pdf), str(scan)]
    assert host.events == [
        ("document:open", {"path": str(pdf), "password": None}),
        ("images:open", {"paths": [str(photo), str(scan)]}),
    ]
    # La ventana lee cada imagen con una URL de un solo uso; un PDF no se lee así.
    url = docs.image_url(str(photo))
    assert base64.b64decode(url.split(",", 1)[1]) == photo.read_bytes()
    with pytest.raises(UserError):
        docs.image_url(str(pdf))
    with pytest.raises(UserError):
        docs.image_url(str(tmp_path / "no_existe.png"))


def test_the_window_and_python_accept_the_same_images():
    """El selector y el arrastre de la ventana (escritorio y navegador) aceptan las imágenes de ``documents``."""
    files = (UI / "lib" / "browser" / "files.ts").read_text(encoding="utf-8")
    pick = (UI / "lib" / "images" / "pick.ts").read_text(encoding="utf-8")
    for suffix in IMAGE_SUFFIXES:
        assert f"'{suffix}'" in files, suffix
        assert f"{suffix}," in pick or f"{suffix}'" in pick, suffix


# ── El PDF de las imágenes ──────────────────────────────────────────────────
def test_a_jpg_goes_as_is_and_follows_its_exif_orientation():
    # foto_exif6.jpg: 60×40 guardada (izquierda roja, derecha azul) con orientación EXIF 6 (girar
    # 90° a la derecha para verla): se ve 40×60, arriba roja y abajo azul.
    data = _images_pdf([_image("foto_exif6.jpg", 40, 60, margin="none", fit="cover")])
    jpeg = (FIXTURES / "foto_exif6.jpg").read_bytes()
    assert jpeg in data  # tal cual: sin recomprimir
    with Document.open(data) as doc:
        assert len(doc) == 1
        width, height = doc[0].rect.width, doc[0].rect.height
        assert (round(width, 1), round(height, 1)) == (round(A4[0], 1), round(A4[1], 1))  # vertical: la imagen lo es
        assert _reddish(_color(doc, 0, 0.5, 0.1)) and _bluish(_color(doc, 0, 0.5, 0.9))


def test_page_options_rotation_and_margins():
    # Girada 90° más (180° en total desde como está guardada): izquierda azul, derecha roja.
    # Horizontal, en Carta y con margen.
    data = _images_pdf([
        _image("foto_exif6.jpg", 40, 60, rotation=90, paper="letter", margin="wide"),
        _image("gris.jpg", 30, 20, paper="image"),
        _image("gris.jpg", 30, 20, paper="a5", orientation="portrait", margin="normal"),
    ])
    with Document.open(data) as doc:
        assert len(doc) == 3
        rects = [(round(p.rect.width), round(p.rect.height)) for p in doc]
        assert rects[0] == (792, 612)  # Carta horizontal: la imagen girada es más ancha que alta
        assert rects[1] == (842, 561)  # «igual que la imagen»: 3:2 con el lado mayor de un A4
        assert rects[2] == (420, 595)  # A5 vertical aunque la imagen sea horizontal
        # Carta con margen amplio (20 mm ≈ 57 pt): la imagen 60×40 encaja de alto (612 - 2·57).
        assert _bluish(_color(doc, 0, 0.3, 0.5)) and _reddish(_color(doc, 0, 0.7, 0.5))
        assert _color(doc, 0, 0.5, 0.02) == (255, 255, 255)  # el margen queda en blanco
        assert _color(doc, 0, 0.05, 0.5) == (255, 255, 255)  # y los lados (encaja, no rellena)
        gray = _color(doc, 1, 0.5, 0.5)
        assert all(abs(c - 128) < 12 for c in gray)


# ── El documento nuevo ──────────────────────────────────────────────────────
def test_viewer_create_opens_an_untitled_document_that_saves_as(tmp_path):
    data = _images_pdf([_image("foto_exif6.jpg", 40, 60), _image("gris.jpg", 30, 20)])
    host = FakeHost(save_to=str(tmp_path / "fotos"))
    svc = ViewerService(host)
    try:
        info = svc.create("Imágenes.pdf", _put(svc, data))
        assert info["untitled"] and info["modified"] and info["name"] == "Imágenes.pdf"
        assert len(info["pages"]) == 2 and len(info["keys"]) == 2
        assert recent_files.load(lambda _p: True) == []  # sin archivo no entra en recientes
        assert svc.unsaved_documents() == ["Imágenes.pdf"]
        assert svc.file_size(info["id"]) == len(data)
        other = svc.create("Imágenes.pdf", _put(svc, data))  # otro con el mismo nombre
        assert other["name"] == "Imágenes (2).pdf"
        svc.close_document(other["id"])

        viewer = FakeViewer(svc, info["id"])  # EmbedPDF lo abre de lo que guarda Python
        assert viewer.data == data and viewer.keys == info["keys"]
        with pytest.raises(UserError) as error:
            viewer.save("save")  # aún no tiene archivo: el visor usa «Guardar como»
        assert error.value.code == "untitled"
        saved = viewer.save("save_as")
        assert saved["path"] == str(tmp_path / "fotos.pdf") and not saved["untitled"] and not saved["modified"]
        assert host.saved_suggestions[-1].endswith("Imágenes.pdf")
        assert (tmp_path / "fotos.pdf").read_bytes() == data
        assert [Path(p).name for p in recent_files.load()] == ["fotos.pdf"]
        assert svc.file_size(info["id"]) == len(data)
        assert viewer.save("save")["name"] == "fotos.pdf"  # ya tiene archivo: Ctrl+S guarda en él
    finally:
        svc.close()


def test_viewer_create_rejects_what_is_not_a_pdf(tmp_path):
    svc = ViewerService(FakeHost())
    with pytest.raises(UserError):
        svc.create("x.pdf", _put(svc, b"no es un pdf"))


# ── Insertar y rehacer páginas con el motor del visor ───────────────────────
def test_image_pages_are_inserted_and_replaced_by_the_engine(tmp_path):
    images = tmp_path / "imagenes.pdf"
    images.write_bytes(_images_pdf([_image("gris.jpg", 30, 20), _image("foto_exif6.jpg", 40, 60)]))
    single = tmp_path / "una.pdf"
    single.write_bytes(_images_pdf([_image("foto_exif6.jpg", 40, 60, paper="a5")]))
    base = pdf_bytes([[(72, 72, "uno")], [(72, 72, "dos")]])

    inserted = run_engine("pages", base, {"ops": [["insert-pdf", 0, str(images)]]})
    assert page_texts(inserted) == ["uno", "", "", "dos"]  # detrás de la página 1
    with Document.open(inserted) as doc:
        assert _bluish(_color(doc, 2, 0.5, 0.9))

    replaced = run_engine("pages", inserted, {"ops": [["replace-pdf", 1, str(single)]]})
    with Document.open(replaced) as doc:
        assert len(doc) == 4
        assert round(doc[1].rect.width) == 420  # el A5 en el sitio de la página
        assert _reddish(_color(doc, 1, 0.5, 0.1))


# ── Exportar las páginas como imágenes ──────────────────────────────────────
def test_page_images_are_written_only_in_the_chosen_folder(tmp_path):
    pdf = _make_pdf(tmp_path / "informe.pdf", 2)
    out = tmp_path / "salida"
    out.mkdir()
    host = FakeHost(folder=str(out))
    svc = ViewerService(host)
    try:
        doc_id = svc.open(str(pdf))["id"]
        assert svc.pick_images_folder(doc_id) == {"folder": str(out), "stem": "informe"}
        svc.save_page_image(str(out), "informe_p1.png", _put(svc, b"png"))
        svc.save_page_image(str(out), "informe_p2.jpg", _put(svc, b"jpg"))
        assert sorted(p.name for p in out.iterdir()) == ["informe_p1.png", "informe_p2.jpg"]
        for folder, name in [
            (str(tmp_path), "informe_p1.png"),  # una carpeta que no eligió el usuario
            (str(out), "../fuera.png"),  # fuera de la carpeta
            (str(out), "informe.exe"),  # lo que no es una imagen
        ]:
            with pytest.raises(UserError):
                svc.save_page_image(folder, name, _put(svc, b"x"))
        assert not (tmp_path / "fuera.png").exists()
        host.folder = None
        assert svc.pick_images_folder(doc_id) is None  # cancelado
    finally:
        svc.close()


def test_the_viewer_menu_offers_the_image_actions():
    menu = json.dumps((UI / "tools" / "viewer" / "document" / "operations.ts").read_text(encoding="utf-8"))
    for action in ("insertImages", "adjustImage", "exportPageImages"):
        assert f"M.{action}" in menu, action
