"""``installer/changelog.py``: las secciones de CHANGELOG.md (docs/web/versiones.md)."""
from __future__ import annotations

import pytest

from app import APP_VERSION
from installer import changelog

TEXT = "# Changelog\n\n## [0.2.0-web] - 2026-12-01\n\n### Added\n- Dos\n\n## [0.1.0] - 2026-01-01\n\n### Fixed\n- Uno\n"


def test_section_gives_one_version_without_its_title():
    assert changelog.section(TEXT, "0.2.0-web") == "### Added\n- Dos"
    assert changelog.section(TEXT, "0.1.0") == "### Fixed\n- Uno"


def test_section_is_none_when_the_version_is_missing():
    assert changelog.section(TEXT, "0.2.0") is None  # «0.2.0» no es «0.2.0-web»
    assert changelog.section(TEXT, "9.9.9") is None


def test_section_reads_windows_line_endings():
    assert changelog.section(TEXT.replace("\n", "\r\n"), "0.1.0") == "### Fixed\n- Uno"


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_insert_puts_the_new_section_under_the_title_and_keeps_the_rest(ending):
    result = changelog.insert(TEXT.replace("\n", ending), "## [0.3.0-web] - 2026-12-24\n\n### Added\n- Tres\n")
    assert result.startswith("# Changelog\n\n## [0.3.0-web] - 2026-12-24\n\n### Added\n- Tres\n\n## [0.2.0-web]")
    assert result.count("# Changelog") == 1
    assert changelog.section(result, "0.2.0-web") == "### Added\n- Dos"
    assert changelog.section(result, "0.1.0") == "### Fixed\n- Uno"


def test_app_version_is_the_one_the_app_reports():
    assert changelog.app_version() == APP_VERSION


def test_notes_fail_for_a_version_without_section(capsys):
    with pytest.raises(SystemExit) as failure:
        changelog.main(["notes", "9.9.9"])
    assert "9.9.9" in str(failure.value)


def test_notes_print_the_section_of_a_published_version(capsys):
    assert changelog.main(["notes", "v0.1.28"]) == 0  # con o sin la «v» de la etiqueta
    assert "Última versión con Flet" in capsys.readouterr().out
