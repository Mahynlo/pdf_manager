"""Tests para `pdf_viewer._text_legends` — persistencia de leyendas (textos).

Se aísla el archivo JSON con un tmp_path por test para no tocar el del usuario.
"""
from __future__ import annotations

import pdf_viewer._text_legends as legends_mod
from pdf_viewer._text_legends import LegendManager, TextLegend


def _mgr(tmp_path, monkeypatch) -> LegendManager:
    monkeypatch.setattr(legends_mod, "_LEGENDS_FILE", tmp_path / "legends.json")
    return LegendManager()


def test_create_and_get(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("Confidencial", "Documento confidencial")
    assert lg.id
    assert mgr.get(lg.id).text == "Documento confidencial"
    assert len(mgr.all()) == 1


def test_persists_across_instances(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    mgr.create("Revisado", "Revisado por…")
    # Una instancia nueva debe leer el mismo archivo.
    mgr2 = LegendManager()
    assert [x.name for x in mgr2.all()] == ["Revisado"]


def test_update(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("A", "texto a")
    assert mgr.update(lg.id, name="B", text="texto b") is True
    got = mgr.get(lg.id)
    assert got.name == "B" and got.text == "texto b"
    assert mgr.update("inexistente", name="x") is False


def test_update_blank_name_keeps_old(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("Nombre", "t")
    mgr.update(lg.id, name="   ")
    assert mgr.get(lg.id).name == "Nombre"


def test_delete(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("X", "y")
    assert mgr.delete(lg.id) is True
    assert mgr.all() == []
    assert mgr.delete(lg.id) is False


def test_search_by_name_and_text(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    mgr.create("Aprobado", "Sello de aprobación")
    mgr.create("Borrador", "documento en revisión")
    assert [x.name for x in mgr.search("aprob")] == ["Aprobado"]   # por nombre
    assert [x.name for x in mgr.search("revisión")] == ["Borrador"]  # por texto
    assert len(mgr.search("")) == 2  # sin query → todas


def test_empty_name_defaults(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("   ", "contenido")
    assert lg.name == "Sin nombre"


def test_roundtrip_dict():
    lg = TextLegend(
        id="1", name="N", text="multi\nlínea",
        fontname="tibo", fontsize=18.0, color=(0.1, 0.2, 0.3), align=2,
        border_width=2.5, use_count=3, last_used=12.5,
    )
    assert TextLegend.from_dict(lg.to_dict()) == lg


def test_legacy_dict_without_usage_defaults_zero():
    lg = TextLegend.from_dict({"id": "1", "name": "N", "text": "t"})
    assert lg.use_count == 0 and lg.last_used == 0.0


def test_legacy_dict_without_style_uses_defaults():
    # Una leyenda antigua (solo texto) debe cargar con el estilo por defecto.
    lg = TextLegend.from_dict({"id": "1", "name": "N", "text": "t"})
    assert lg.fontname == "helv"
    assert lg.fontsize == 14.0
    assert lg.color == (0.0, 0.0, 0.0)
    assert lg.align == 0
    assert lg.border_width == 0.0


def test_create_persists_style(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create(
        "Conf", "Confidencial",
        fontname="tibo", fontsize=20, color=(0.8, 0, 0), align=1, border_width=1.5,
    )
    got = LegendManager().get(lg.id)  # releído de disco
    assert got.fontname == "tibo"
    assert got.fontsize == 20.0
    assert got.color == (0.8, 0.0, 0.0)
    assert got.align == 1
    assert got.border_width == 1.5


def test_update_style(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("A", "a")
    mgr.update(lg.id, align=2, border_width=3.0, fontname="cour")
    got = mgr.get(lg.id)
    assert got.align == 2 and got.border_width == 3.0 and got.fontname == "cour"


def test_style_props_shape(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("A", "hola", fontname="heit", fontsize=16, align=2, border_width=1.0)
    props = lg.style_props()
    assert props == {
        "text": "hola", "fontname": "heit", "fontsize": 16.0,
        "color": (0.0, 0.0, 0.0), "align": 2, "border_width": 1.0,
    }


def test_bump_usage_increments_and_persists(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    lg = mgr.create("X", "y")
    assert mgr.bump_usage(lg.id) is True
    assert mgr.bump_usage(lg.id) is True
    assert mgr.get(lg.id).use_count == 2
    assert mgr.get(lg.id).last_used > 0.0
    # Persiste en disco.
    assert LegendManager().get(lg.id).use_count == 2
    assert mgr.bump_usage("inexistente") is False


def test_most_used_orders_by_count(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    a = mgr.create("A", "a")
    b = mgr.create("B", "b")
    c = mgr.create("C", "c")
    for _ in range(3):
        mgr.bump_usage(b.id)
    mgr.bump_usage(c.id)
    # b (3) > c (1) > a (0)
    assert [x.name for x in mgr.most_used()] == ["B", "C", "A"]


def test_most_used_respects_limit(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    for i in range(8):
        mgr.create(f"L{i}", "t")
    assert len(mgr.most_used(5)) == 5
    assert len(mgr.most_used(0)) == 8  # 0 → sin límite


def test_most_used_tiebreak_by_recency(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    a = mgr.create("A", "a")
    b = mgr.create("B", "b")
    # Mismo use_count pero B se usó después → B primero (desempate determinista).
    a.use_count = b.use_count = 1
    a.last_used, b.last_used = 100.0, 200.0
    assert [x.name for x in mgr.most_used()][:2] == ["B", "A"]
