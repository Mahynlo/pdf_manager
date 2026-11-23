"""Caracteres que no caben: contraseñas nuevas de un PDF (SASLprep, ``password_problem``), claves de
API (ASCII visible) y el texto libre y las leyendas, que se escriben con las fuentes estándar de
PDF (``lib/standard-font.ts``): un emoji dejaría la anotación entera en blanco."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pdfkit import pdf_bytes, run_engine

from app.backend.rpc import UserError
from app.backend.services.ai import AiService
from app.backend.services.security import SecurityService
from pdf_core.pdf import Document
from pdf_core.security import MAX_PASSWORD_BYTES, password_problem

UI = Path(__file__).resolve().parents[1] / "app" / "ui"


# ── Contraseñas nuevas ──────────────────────────────────────────────────────
@pytest.mark.parametrize("password", [
    "clave123", "contraseña", "Contraseña Segura 2026!", "пароль", "密码", "שלום", "a" * MAX_PASSWORD_BYTES,
])
def test_passwords_any_pdf_reader_can_use(password):
    assert password_problem(password) is None


@pytest.mark.parametrize(("password", "why"), [
    ("clave😀", "emojis"),
    ("✅🔒", "emojis"),
    ("a​b", "invisibles"),  # espacio de ancho cero (al pegar)
    ("a­b", "invisibles"),  # guion suave
    ("x\x07", "invisibles"),
    ("ñandú café", "distinto"),  # espacio de no separación: SASLprep lo cambia
    ("Ａｂｃ１２３", "distinto"),  # ancho completo: NFKC lo cambia
    ("שלוםabc", "derecha a izquierda"),
    ("a" * (MAX_PASSWORD_BYTES + 1), "larga"),
    ("ñ" * 64, "larga"),  # 128 bytes en UTF-8
])
def test_passwords_that_could_lock_the_pdf(password, why):
    problem = password_problem(password)
    assert problem and why in problem


def test_emoji_password_breaks_saslprep_but_the_engine_would_accept_it():
    """Por qué se rechazan: el motor cifra con un emoji y PDFium lo abre, pero SASLprep (la norma)
    no lo admite, y un lector que la siga (Acrobat) podría no abrirlo."""
    data = run_engine("encrypt", pdf_bytes([[(72, 72, "hola")]]), {"user": "clave😀", "owner": "x", "permissions": -1})
    with Document.open(data, "clave😀") as doc:
        assert doc[0].text().strip() == "hola"
    assert password_problem("clave😀")


class _Host:
    def __init__(self, dest: Path) -> None:
        self.dest = dest
        self.engine_calls = 0

    def save_pdf(self, _suggested: str) -> str:
        return str(self.dest)

    def run_engine(self, task: str, data: bytes, args: dict) -> bytes:
        self.engine_calls += 1
        return run_engine(task, data, args)


def test_protect_rejects_passwords_before_encrypting(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(pdf_bytes([[(72, 72, "hola")]]))
    host = _Host(tmp_path / "protegido.pdf")
    service = SecurityService(host, None)  # type: ignore[arg-type]  (proteger no usa documents)
    for user, owner, field in [("clave😀", "", "apertura"), ("buena", "dueño​", "propietario")]:
        with pytest.raises(UserError) as error:
            service.protect(str(source), user, owner, {})
        assert error.value.code == "invalid_password" and field in str(error.value)
    assert host.engine_calls == 0 and not host.dest.exists()
    assert service.protect(str(source), "contraseña", "", {}) == str(host.dest)
    with Document.open(host.dest.read_bytes(), "contraseña") as doc:
        assert doc[0].text().strip() == "hola"


# ── Claves de API ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", ["sk-abc 123", "sk-abc😀", "sk-​abc", "clavé", "x" * 600])
def test_api_keys_only_take_visible_ascii(key, monkeypatch):
    from pdf_core.agent import config as agent_config

    saved = []
    monkeypatch.setattr(agent_config, "set_api_key", lambda *args: saved.append(args))
    service = AiService.__new__(AiService)
    with pytest.raises(UserError) as error:
        service.set_config("openai", key)
    assert error.value.code == "bad_key" and not saved


# ── Texto libre y leyendas ──────────────────────────────────────────────────
def _standard_font_text(texts: list[str]) -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("hace falta Node")
    module = (UI / "src" / "lib" / "standard-font.ts").as_uri()
    script = (f"import {{ standardFontText }} from '{module}';"
              f"console.log(JSON.stringify({json.dumps(texts)}.map(standardFontText)));")
    done = subprocess.run(["node", "--no-warnings", "--input-type=module", "-e", script],
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def test_standard_font_text_keeps_what_the_font_has():
    cleaned = _standard_font_text(["Hola ñandú café €", "Pagado ✅ 😀", "Peso 5 kg ✓", "Ελληνικά", "👍🏽 ok", "uno\ndos"])
    assert cleaned[0] == {"text": "Hola ñandú café €", "removed": []}
    assert cleaned[1] == {"text": "Pagado  ", "removed": ["✅", "😀"]}
    assert cleaned[2]["text"] == "Peso 5 kg " and cleaned[2]["removed"] == ["✓"]
    assert cleaned[3]["text"].strip() == ""
    assert cleaned[4] == {"text": " ok", "removed": ["👍🏽"]}  # el emoji con tono de piel, entero
    assert cleaned[5]["text"] == "uno\ndos"


def _dark_rows(data: bytes) -> list[bool]:
    """Si cada caja de texto (una por fila, ver la tarea «freetext») tiene algo escrito."""
    with Document.open(data) as doc:
        image = doc[0].render(1.0)
    rows = []
    for i in range(3):
        top = 40 + i * 60  # puntos desde arriba (render a 1.0: un píxel por punto)
        band = image[top:top + 40, 40:440, :3]
        rows.append(bool((band.min(axis=2) < 100).sum() > 20))
    return rows


def test_an_emoji_blanks_free_text_unless_it_is_removed():
    texts = ["Hola ñandú", "Pagado ✅ 😀", "Peso 5 kg ✓"]
    base = pdf_bytes([[]])
    assert _dark_rows(run_engine("freetext", base, {"texts": texts})) == [True, False, False]
    assert _dark_rows(run_engine("freetext", base, {"texts": texts, "clean": True})) == [True, True, True]


def test_the_viewer_cleans_free_text_and_legends():
    ui = UI / "src" / "tools" / "viewer"
    annotations = (ui / "annotations" / "annotations.ts").read_text(encoding="utf-8")
    assert "_standardText(event.pageIndex" in annotations and "standardFontText(stamp.text)" in annotations
    assert "standardFontText(text).removed" in (ui / "stamps" / "LegendsDialog.svelte").read_text(encoding="utf-8")
    field = (UI / "src" / "lib" / "components" / "PasswordField.svelte").read_text(encoding="utf-8")
    assert 'spellcheck="false"' in field  # al mostrarla, el corrector no la lee
