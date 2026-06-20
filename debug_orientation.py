"""Diagnostico de orientacion nativa.
Uso:  uv run python debug_orientation.py  [ruta_pdf]
Sin argumento usa PDFs de prueba internos.
"""
import sys, tempfile, os
import fitz

def check(page, label=""):
    rotation = page.rotation
    W, H = page.rect.width, page.rect.height
    print(f"\n{'='*55}")
    if label:
        print(f"  {label}")
    print(f"  rotation={rotation}  W={W:.0f}  H={H:.0f}")

    blocks = page.get_text("blocks")
    ys = []
    print(f"  Bloques de texto (y pre-rot  ->  display_y):")
    for b in blocks:
        if b[6] != 0 or not b[4].strip():
            continue
        cy = (b[1] + b[3]) / 2
        dy = (H - cy) if rotation == 180 else cy
        ys.append(dy)
        print(f"    cy={cy:.1f}  display_y={dy:.1f}  '{b[4].strip()[:45]}'")

    if not ys:
        print("  (sin bloques de texto)")
        return

    bottom = sum(1 for y in ys if y > H / 2)
    pct = bottom / len(ys)
    print(f"\n  bloques en mitad inferior: {bottom}/{len(ys)} = {pct:.0%}")
    decision = 180 if pct >= 0.65 else 0
    print(f"  detect_orientation_native  -> {decision} grados")
    correccion = (rotation + decision) % 360
    print(f"  correccion: set_rotation(({rotation}+{decision})%360 = {correccion})")


# PDFs de prueba internos
tmp = tempfile.gettempdir()

p0   = os.path.join(tmp, "t_normal.pdf")
p180 = os.path.join(tmp, "t_rot180.pdf")

doc = fitz.open(); pg = doc.new_page()
pg.insert_text((72, 100), "Linea 1 texto normal", fontsize=14)
pg.insert_text((72, 130), "Linea 2 texto normal", fontsize=12)
pg.insert_text((72, 160), "Linea 3 texto normal", fontsize=12)
doc.save(p0); doc.close()

doc = fitz.open(); pg = doc.new_page()
pg.insert_text((72, 100), "Linea 1 con /Rotate 180", fontsize=14)
pg.insert_text((72, 130), "Linea 2 con /Rotate 180", fontsize=12)
pg.insert_text((72, 160), "Linea 3 con /Rotate 180", fontsize=12)
pg.set_rotation(180)
doc.save(p180); doc.close()

if len(sys.argv) > 1:
    path = sys.argv[1]
    doc = fitz.open(path)
    for i in range(min(3, len(doc))):
        check(doc[i], f"Pagina {i+1} de {path}")
    doc.close()
else:
    for path, label in [(p0, "Normal 0"), (p180, "/Rotate 180")]:
        doc = fitz.open(path)
        check(doc[0], label)
        doc.close()
