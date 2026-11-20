"""Genera las imágenes del asistente de instalación (installer/web/images/*.bmp).

    uv run --no-project --with pillow python installer/web/make_images.py

Solo hace falta al cambiar el logo o los colores: las imágenes se suben al repositorio y setup.iss
las usa tal cual. Cada una va en tamaño normal (100 %) y doble (200 %): Inno Setup elige la que
mejor encaja con la escala de la pantalla. Pillow solo hace falta aquí, no en la app.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
LOGO = ROOT / "app" / "ui" / "src" / "assets" / "logo.png"
OUT = Path(__file__).resolve().parent / "images"
FONTS = Path("C:/Windows/Fonts")

TOP, BOTTOM = (0xB7, 0x1C, 0x1C), (0xD3, 0x2F, 0x2F)  # rojo de la marca (tokens.css: --brand)
WHITE = (255, 255, 255)
SOFT = (255, 225, 225)


def font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default()


def centered(draw: ImageDraw.ImageDraw, width: int, y: int, text: str, face, fill) -> None:
    left, _, right, _ = draw.textbbox((0, 0), text, font=face)
    draw.text(((width - (right - left)) / 2, y), text, font=face, fill=fill)


def side_panel(scale: int) -> Image.Image:
    """Panel de la bienvenida y el final (164 × 314 a 100 %)."""
    w, h = 164 * scale, 314 * scale
    image = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(image)
    for y in range(h):  # degradado vertical
        t = y / (h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM, strict=True)))
    # Logo sobre un círculo blanco
    radius = 52 * scale
    cx, cy = w // 2, 104 * scale
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=WHITE)
    size = 76 * scale
    logo = Image.open(LOGO).convert("RGBA").resize((size, size), Image.LANCZOS)
    image.paste(logo, (cx - size // 2, cy - size // 2), logo)
    centered(draw, w, 176 * scale, "Extraer PDFs", font("segoeuib.ttf", 19 * scale), WHITE)
    for i, line in enumerate(("Ver · anotar · censurar", "OCR · combinar · proteger")):
        centered(draw, w, (210 + i * 17) * scale, line, font("segoeui.ttf", 10 * scale), SOFT)
    return image


def header_icon(scale: int) -> Image.Image:
    """Icono de la cabecera de cada página (55 × 58 a 100 %)."""
    w, h = 55 * scale, 58 * scale
    image = Image.new("RGB", (w, h), WHITE)
    size = 48 * scale
    logo = Image.open(LOGO).convert("RGBA").resize((size, size), Image.LANCZOS)
    image.paste(logo, ((w - size) // 2, (h - size) // 2), logo)
    return image


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for scale in (1, 2):
        suffix = "" if scale == 1 else "@2x"
        side_panel(scale).save(OUT / f"wizard{suffix}.bmp")
        header_icon(scale).save(OUT / f"wizard-small{suffix}.bmp")
    print("Imágenes en", OUT)


if __name__ == "__main__":
    main()
