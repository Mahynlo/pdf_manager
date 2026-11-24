"""Capturas de pantalla de la Ayuda (``src/assets/ayuda_img/``), con un número sobre cada parte.

Las guías (``src/assets/ayuda/``) explican cada número. Se hacen sobre la versión de navegador,
con un PDF de ejemplo creado aquí (nada personal en «Archivos recientes»). Cuando cambie la
interfaz, se vuelven a generar:

    cd app/ui && pnpm build:web && pnpm preview:web          # en otra terminal (puerto 5174)
    uv run --with playwright python installer/ayuda/capturas.py

Usa el Edge del sistema (Playwright no descarga ningún navegador).
"""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from pdfkit import add_page, add_text  # noqa: E402  (PDF de ejemplo con el motor del proyecto)

from pdf_core.pdf import Document  # noqa: E402

OUT = ROOT / "src" / "assets" / "ayuda_img"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5174/"

# Números y recuadros sobre la captura: [selector, número, dónde va el número: «left» (esquina de
# arriba a la izquierda), «right», «bottom», «center» o «inside» (dentro, a la izquierda)].
MARKS_JS = """
(marks) => {
  const layer = document.createElement('div');
  layer.id = 'help-marks';
  layer.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9999';
  for (const [selector, n, at] of marks) {
    const el = [...document.querySelectorAll(selector)].find((e) => e.getClientRects().length);
    if (!el) { console.warn('sin', selector); continue; }
    const r = el.getBoundingClientRect();
    const box = document.createElement('div');
    box.style.cssText = `position:fixed;left:${r.left - 3}px;top:${r.top - 3}px;width:${r.width + 6}px;`
      + `height:${r.height + 6}px;border:2px solid #E53935;border-radius:8px`;
    const badge = document.createElement('div');
    const size = 24;
    let x = r.left - size / 2, y = r.top - size / 2;
    if (at === 'right') x = r.right - size / 2;
    if (at === 'bottom') y = r.bottom - size / 2;
    if (at === 'center') { x = r.left + r.width / 2 - size / 2; y = r.top + r.height / 2 - size / 2; }
    if (at === 'inside') { x = r.left + 8; y = r.top + Math.min(r.height / 2 - size / 2, 40); }
    x = Math.max(2, Math.min(innerWidth - size - 2, x));
    y = Math.max(2, Math.min(innerHeight - size - 2, y));
    badge.textContent = n;
    badge.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:${size}px;height:${size}px;`
      + 'display:grid;place-items:center;border-radius:50%;background:#E53935;color:#fff;'
      + 'font:700 13px Segoe UI,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.4);border:2px solid #fff';
    layer.append(box, badge);
  }
  // Un diálogo modal está en la capa superior: los números van dentro para verse encima.
  (document.querySelector('dialog[open]') ?? document.body).append(layer);
}
"""


def sample_pdf(path: Path, title: str, pages: int = 3) -> Path:
    """Un PDF de ejemplo con título, párrafos y páginas numeradas."""
    lines = [
        "Las partes acuerdan la prestación del servicio descrito en este documento.",
        "El proveedor entregará los trabajos en las fechas indicadas en el anexo.",
        "El cliente pagará el importe total en dos plazos: al firmar y al terminar.",
        "Cualquier cambio en el alcance se acordará por escrito entre ambas partes.",
        "Este contrato se rige por la legislación vigente en la fecha de su firma.",
    ]
    with Document.new() as doc:
        for n in range(1, pages + 1):
            page = add_page(doc)
            add_text(page, 72, 90, title if n == 1 else f"{title} (continuación)", 20)
            add_text(page, 72, 120, f"Página {n} de {pages}", 10)
            y = 170
            for i in range(14):
                add_text(page, 72, y, f"{i + 1}. {lines[(i + n) % len(lines)]}", 11)
                y += 26
            add_text(page, 72, 780, "Firma del cliente: ____________________", 11)
        path.write_bytes(doc.to_bytes())
    return path


def visible(page: Page, selector: str):
    """El primero visible (cada pestaña de PDF tiene su visor: solo se ve el de la activa)."""
    return page.locator(selector).locator("visible=true").first


# Imágenes de ejemplo para «Imágenes a PDF»: una foto de un recibo (vertical) y un paisaje
# (horizontal), dibujadas en un lienzo del navegador.
SAMPLE_IMAGES_JS = """
() => {
  const receipt = document.createElement('canvas');
  receipt.width = 600; receipt.height = 900;
  let c = receipt.getContext('2d');
  c.fillStyle = '#8D6E63'; c.fillRect(0, 0, 600, 900);
  c.fillStyle = '#FFFDF7'; c.fillRect(70, 60, 460, 780);
  c.fillStyle = '#333'; c.font = 'bold 40px Segoe UI'; c.fillText('RECIBO', 220, 140);
  c.font = '22px Segoe UI';
  ['Café ........ 2,50', 'Tostada ..... 3,00', 'Zumo ........ 2,80', 'Agua ........ 1,20'].forEach((t, i) => c.fillText(t, 130, 240 + i * 50));
  c.font = 'bold 26px Segoe UI'; c.fillText('TOTAL ...... 9,50', 130, 500);
  c.fillStyle = '#999'; c.font = '18px Segoe UI'; c.fillText('Gracias por su visita', 200, 700);
  const landscape = document.createElement('canvas');
  landscape.width = 960; landscape.height = 600;
  c = landscape.getContext('2d');
  const sky = c.createLinearGradient(0, 0, 0, 380); sky.addColorStop(0, '#4FC3F7'); sky.addColorStop(1, '#E1F5FE');
  c.fillStyle = sky; c.fillRect(0, 0, 960, 600);
  c.fillStyle = '#FFD54F'; c.beginPath(); c.arc(760, 130, 60, 0, 7); c.fill();
  c.fillStyle = '#78909C'; c.beginPath(); c.moveTo(0, 420); c.lineTo(260, 170); c.lineTo(520, 420); c.fill();
  c.fillStyle = '#90A4AE'; c.beginPath(); c.moveTo(300, 420); c.lineTo(600, 210); c.lineTo(960, 420); c.fill();
  c.fillStyle = '#66BB6A'; c.fillRect(0, 400, 960, 200);
  return [receipt.toDataURL('image/png'), landscape.toDataURL('image/png')];
}
"""


Mark = tuple[str | Locator, int, str]


def mark(page: Page, marks: list[Mark]) -> None:
    """Pone los números. Un ``Locator`` (p. ej. por el texto de un botón) se marca antes con un atributo."""
    plain = []
    for target, n, at in marks:
        if not isinstance(target, str):
            target.evaluate("(e, n) => e.setAttribute('data-help-mark', n)", str(n))
            target = f"[data-help-mark='{n}']"
        plain.append([target, n, at])
    page.evaluate(MARKS_JS, plain)


def unmark(page: Page) -> None:
    page.evaluate("""() => {
      document.getElementById('help-marks')?.remove();
      document.querySelectorAll('[data-help-mark]').forEach((e) => e.removeAttribute('data-help-mark'));
    }""")


def shot(page: Page, name: str, marks: list[Mark], clip: dict | None = None) -> None:
    mark(page, marks)
    page.wait_for_timeout(150)
    page.screenshot(path=str(OUT / name), clip=clip)
    unmark(page)
    print("✓", name)


def open_files(page: Page, files: list[Path], trigger) -> None:
    with page.expect_file_chooser() as chooser:
        trigger()
    chooser.value.set_files([str(f) for f in files])


def start(browser, width: int, height: int, touch: bool = False) -> Page:
    context = browser.new_context(viewport={"width": width, "height": height}, color_scheme="light",
                                  has_touch=touch, is_mobile=touch, device_scale_factor=2 if touch else 1)
    # Sin los selectores de archivos del sistema: el de la página (lo maneja Playwright).
    context.add_init_script("delete window.showOpenFilePicker; delete window.showSaveFilePicker; delete window.showDirectoryPicker;")
    page = context.new_page()
    page.goto(URL)
    page.locator(".home-card").first.wait_for(timeout=120_000)
    page.wait_for_timeout(500)
    return page


def open_pdf(page: Page, pdf: Path) -> None:
    open_files(page, [pdf], lambda: page.keyboard.press("Control+o"))
    page.locator(".pdf-page").first.wait_for(timeout=60_000)
    page.wait_for_timeout(1200)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ayuda-"))
    contract = sample_pdf(tmp / "Contrato de servicios.pdf", "Contrato de servicios")
    report = sample_pdf(tmp / "Informe anual.pdf", "Informe anual", 2)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)

        # ── Inicio ────────────────────────────────────────────────────────
        page = start(browser, 1280, 720)
        open_pdf(page, report)
        open_pdf(page, contract)
        page.locator(".tab", has_text="Inicio").click()
        page.wait_for_timeout(500)
        shot(page, "inicio.png", [
            (".brand", 1, "left"), (".tabstrip", 2, "left"), (".home-open", 3, "left"),
            (".home__cards", 4, "left"), (".recent", 5, "inside"),
        ])

        # ── Visor ─────────────────────────────────────────────────────────
        page.locator(".tab", has_text="Contrato").click()
        page.wait_for_timeout(600)
        visible(page, ".viewer-toolbar--main .tb-annotate:not(.tb-menu-btn)").click()
        page.wait_for_timeout(400)
        top = ".viewer-toolbar--main"
        shot(page, "visor.png", [
            (f"{top} button[aria-label^='Más opciones']", 1, "left"),
            (f"{top} .tb-page", 2, "left"),
            (f"{top} .tb-zoom", 3, "left"),
            (f"{top} .tb-nav", 4, "left"),
            (f"{top} button[aria-label^='Scroll continuo']", 5, "left"),
            (f"{top} button[aria-label^='Deshacer']", 6, "left"),
            (f"{top} .tb-annotate:not(.tb-menu-btn)", 7, "left"),
            (f"{top} .tb-menu-btn[aria-label^='Páginas']", 8, "left"),
            (f"{top} .tb-menu-btn[aria-label^='Exportar']", 9, "left"),
            (".viewer-toolbar--tools", 10, "inside"),
            (".viewer-sidebar", 11, "inside"),
            (".viewer-rail", 12, "left"),
        ])
        # Con el rectángulo elegido: se ven sus botones de estilo (color, grosor, relleno).
        visible(page, ".viewer-toolbar--tools button[aria-label='Forma: Rectángulo']").click()
        page.mouse.move(640, 500)  # que no quede ningún botón resaltado
        page.wait_for_timeout(300)
        first = visible(page, ".viewer-toolbar--tools .tb-group").bounding_box()
        last = visible(page, ".viewer-toolbar--tools .tb-style").bounding_box()
        shot(page, "barra-anotaciones.png", [
            (".viewer-toolbar--tools [aria-label='Marcar texto']", 1, "left"),
            (".viewer-toolbar--tools [aria-label='Formas']", 2, "left"),
            (".viewer-toolbar--tools [aria-label='Trazos libres']", 3, "left"),
            (".viewer-toolbar--tools [aria-label='Insertar']", 4, "left"),
            (".viewer-toolbar--tools .tb-style", 5, "left"),
        ], clip={"x": first["x"] - 20, "y": first["y"] - 14, "width": last["x"] + last["width"] - first["x"] + 34,
               "height": first["height"] + 26})
        visible(page, ".viewer-toolbar--main button[aria-label^='Seleccionar Texto']").click()

        def panel(label: str, name: str, marks: list[Mark]) -> None:
            visible(page, f".viewer-rail__tab[aria-label^='{label}']").click()
            page.wait_for_timeout(800)
            dock = visible(page, ".viewer-dock").bounding_box()
            rail = visible(page, ".viewer-rail").bounding_box()
            shot(page, name, marks, clip={"x": dock["x"] - 8, "y": dock["y"], "width": dock["width"] + rail["width"] + 8,
                                          "height": dock["height"]})

        visible(page, ".viewer-toolbar--main .tb-annotate:not(.tb-menu-btn)").click()  # cerrar la barra
        panel("Buscar", "panel-buscar.png", [])
        visible(page, ".viewer-dock input").fill("cliente")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
        dock = visible(page, ".viewer-dock").bounding_box()
        rail = visible(page, ".viewer-rail").bounding_box()
        shot(page, "panel-buscar.png", [], clip={"x": dock["x"] - 8, "y": dock["y"], "width": dock["width"] + rail["width"] + 8,
                                                 "height": dock["height"]})
        panel("Sellos", "panel-sellos.png", [])
        visible(page, ".viewer-rail__tab[aria-label^='Censura']").click()
        page.wait_for_timeout(500)
        visible(page, ".viewer-dock input").fill("cliente")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)
        visible(page, ".viewer-rail__tab[aria-label^='Censura']").click()  # se cierra: panel() lo abre
        panel("Censura", "panel-censura.png", [])
        panel("OCR", "panel-ocr.png", [])
        panel("Asistente", "panel-ia.png", [])
        page.context.close()

        # ── Móvil ─────────────────────────────────────────────────────────
        page = start(browser, 390, 780, touch=True)
        open_pdf(page, contract)
        page.locator(".viewer-rail__annotate").tap()
        page.wait_for_timeout(400)
        shot(page, "visor-movil.png", [
            (".viewer-toolbar--main button[aria-label^='Más opciones']", 1, "left"),
            (".viewer-toolbar--main .tb-nav-split", 2, "left"),
            (".viewer-rail__annotate", 3, "left"),
            (".viewer-rail", 4, "right"),
            (".viewer-toolbar--tools", 5, "right"),
        ])
        page.context.close()

        # ── Imágenes a PDF ────────────────────────────────────────────────
        page = start(browser, 1280, 820)
        images = []
        for name, url in zip(("recibo.png", "paisaje.png"), page.evaluate(SAMPLE_IMAGES_JS), strict=True):
            (tmp / name).write_bytes(base64.b64decode(url.split(",", 1)[1]))
            images.append(tmp / name)
        open_files(page, images, lambda: page.locator(".home-card", has_text="Imágenes a PDF").click())
        page.locator(".images-dialog, .dialog").first.wait_for(timeout=30_000)
        page.wait_for_timeout(1500)
        shot(page, "imagenes-dialogo.png", [
            (".images-dialog__options", 1, "left"), (".images-dialog__side", 2, "left"),
            (".images-dialog__preview", 3, "left"), (".images-dialog__page-tools", 4, "left"),
            (".images-dialog__buttons", 5, "left"),
        ])
        page.context.close()

        # ── Herramientas ──────────────────────────────────────────────────
        page = start(browser, 1280, 820)
        page.locator(".home-card", has_text="Combinar").click()
        page.wait_for_timeout(600)
        open_files(page, [contract, report], lambda: page.get_by_role("button", name="Cargar PDFs...").click())
        page.wait_for_timeout(2500)
        button = lambda name: visible(page, f"button:has-text('{name}')")  # noqa: E731
        shot(page, "combinar.png", [
            (button("Cargar PDFs"), 1, "left"),
            (visible(page, "text=Contrato de servicios.pdf"), 2, "left"),
            (visible(page, "text=Paso 2: Vista previa del resultado"), 3, "left"),
            (visible(page, "text=Crear marcadores (TOC)"), 4, "left"),
            (button("Combinar y Guardar"), 5, "left"),
        ])
        page.locator(".tab", has_text="Inicio").click()
        page.locator(".home-card", has_text="Extraer").click()
        page.wait_for_timeout(800)
        visible(page, "textarea").fill("cliente, pago")
        shot(page, "extraer.png", [
            (visible(page, ".tool-page [role=tablist]"), 1, "left"),
            (visible(page, "text=Paso 1: Documento de Referencia"), 2, "left"),
            (visible(page, "text=Paso 2: Patrón de Búsqueda"), 3, "left"),
            (visible(page, "text=Paso 3: Documentos Objetivo"), 4, "left"),
            (button("Iniciar Búsqueda"), 5, "left"),
            (visible(page, "text=Registro de operación"), 6, "left"),
        ])
        page.locator(".tab", has_text="Inicio").click()
        page.locator(".home-card", has_text="Seguridad").click()
        page.wait_for_timeout(600)
        page.get_by_role("tab", name="Proteger").click()
        open_files(page, [contract], lambda: page.get_by_role("button", name="Seleccionar PDF a Proteger").click())
        page.wait_for_timeout(1200)
        shot(page, "seguridad-proteger.png", [
            (visible(page, ".tool-page [role=tablist]"), 1, "left"),
            (button("Seleccionar PDF a Proteger"), 2, "left"),
            (visible(page, "select"), 3, "left"),
            (visible(page, "text=Permisos personalizados avanzados"), 4, "left"),
            (visible(page, "text=Contraseña de Usuario (Para abrir el PDF)"), 5, "left"),
            (button("Cifrar y Guardar PDF"), 6, "left"),
        ])
        page.context.close()
        browser.close()


if __name__ == "__main__":
    main()
