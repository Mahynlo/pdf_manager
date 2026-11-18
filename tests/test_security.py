"""Seguridad de los PDF (``pdf_core.security``): con PDF cifrados de verdad por el motor de EmbedPDF."""
from __future__ import annotations

from pathlib import Path

import pytest
from pdfkit import encrypted, page_texts, pdf_bytes

from pdf_core.pdf import UNRESTRICTED, Document, PasswordError
from pdf_core.security import (
    PDFFileError,
    PDFInvalidPasswordError,
    PDFPasswordRequiredError,
    PDFSecurityError,
    PDFSecurityManager,
)

PRINT = PDFSecurityManager.PDF_PERM_PRINT


@pytest.fixture
def plain_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "plain.pdf"
    path.write_bytes(pdf_bytes([[(72, 100, "Plain content")]]))
    return path


@pytest.fixture
def protected_pdf(plain_pdf: Path, tmp_path: Path) -> Path:
    path = tmp_path / "protected.pdf"
    path.write_bytes(encrypted(plain_pdf.read_bytes(), "user", "owner", PRINT))
    return path


@pytest.fixture
def owner_only_pdf(plain_pdf: Path, tmp_path: Path) -> Path:
    """Se abre sin contraseña, pero tiene restricciones."""
    path = tmp_path / "owner_only.pdf"
    path.write_bytes(encrypted(plain_pdf.read_bytes(), "", "owner", PRINT))
    return path


class TestUnlockToFile:
    def test_output_file_is_not_encrypted(self, protected_pdf, tmp_path):
        out = tmp_path / "unlocked.pdf"
        assert PDFSecurityManager.unlock_pdf_to_file(str(protected_pdf), "user", str(out)) is True
        with Document.open(out) as doc:
            assert not doc.encrypted and doc.permissions == UNRESTRICTED
        assert "Plain content" in page_texts(out)[0]

    def test_wrong_password_raises_invalid(self, protected_pdf, tmp_path):
        with pytest.raises(PDFInvalidPasswordError):
            PDFSecurityManager.unlock_pdf_to_file(str(protected_pdf), "wrong", str(tmp_path / "x.pdf"))


class TestIsProtected:
    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(PDFFileError):
            PDFSecurityManager.is_protected(str(tmp_path / "does_not_exist.pdf"))

    def test_non_pdf_file_raises(self, tmp_path):
        garbage = tmp_path / "not_a_pdf.pdf"
        garbage.write_bytes(b"this is plain text, not a PDF")
        with pytest.raises(PDFFileError):
            PDFSecurityManager.is_protected(str(garbage))

    def test_real_pdfs(self, plain_pdf, protected_pdf):
        assert PDFSecurityManager.is_protected(str(plain_pdf)) is False
        assert PDFSecurityManager.is_protected(str(protected_pdf)) is True


class TestSecurityInfo:
    def test_unprotected_has_no_passwords(self, plain_pdf):
        info = PDFSecurityManager.get_security_info(str(plain_pdf))
        assert not info.is_encrypted and not info.has_user_password and not info.has_owner_password
        assert all(allowed for _text, allowed in info.permission_items())

    def test_fully_protected_has_user_password(self, protected_pdf):
        info = PDFSecurityManager.get_security_info(str(protected_pdf))
        assert info.is_encrypted and info.has_user_password and info.has_owner_password
        assert info.permission_items() == []  # no se conocen sin la contraseña

    def test_owner_only_does_not_claim_user_password(self, owner_only_pdf):
        info = PDFSecurityManager.get_security_info(str(owner_only_pdf))
        assert not info.is_protected and not info.has_user_password and info.has_owner_password
        assert ("Impresión permitida", True) in info.permission_items()
        assert ("Copia de contenido bloqueada", False) in info.permission_items()


class TestCheckPermissions:
    def test_user_session_sees_the_restrictions(self, protected_pdf):
        info = PDFSecurityManager.check_permissions(str(protected_pdf), "user")
        assert info.is_protected and info.permissions & PRINT and not info.permissions & PDFSecurityManager.PDF_PERM_COPY

    def test_owner_session_has_no_restrictions(self, protected_pdf):
        assert PDFSecurityManager.check_permissions(str(protected_pdf), "owner").permissions == UNRESTRICTED

    def test_password_errors(self, protected_pdf):
        with pytest.raises(PDFPasswordRequiredError):
            PDFSecurityManager.check_permissions(str(protected_pdf))
        with pytest.raises(PDFInvalidPasswordError):
            PDFSecurityManager.check_permissions(str(protected_pdf), "wrong")


class TestCanSaveChanges:
    def test_plain_and_owner(self, plain_pdf, protected_pdf):
        with Document.open(plain_pdf) as doc:
            assert PDFSecurityManager.can_save_changes(doc)
        with Document.open(protected_pdf, "owner") as doc:
            assert PDFSecurityManager.can_save_changes(doc)

    def test_user_without_edit_permissions(self, protected_pdf):
        with Document.open(protected_pdf, "user") as doc:
            assert not PDFSecurityManager.can_save_changes(doc)


def test_permission_mask():
    manager = PDFSecurityManager
    assert manager.permission_mask() == 0
    assert manager.permission_mask(allow_print=True, allow_copy=True) == manager.PDF_PERM_PRINT | manager.PDF_PERM_COPY
    assert manager.permission_mask(**manager.get_default_permissions()["sin_restricciones"]) == 4 | 8 | 16 | 32 | 256 | 1024 | 2048


@pytest.mark.parametrize("error", [PDFPasswordRequiredError, PDFInvalidPasswordError, PDFFileError])
def test_errors_share_a_base(error):
    assert issubclass(error, PDFSecurityError)


class TestOpenForViewer:
    def test_plain_pdf_opens_directly(self, plain_pdf):
        with PDFSecurityManager.open_for_viewer(str(plain_pdf)) as doc:
            assert len(doc) == 1

    def test_password_errors(self, protected_pdf):
        with pytest.raises(PDFPasswordRequiredError):
            PDFSecurityManager.open_for_viewer(str(protected_pdf))
        with pytest.raises(PDFInvalidPasswordError):
            PDFSecurityManager.open_for_viewer(str(protected_pdf), password="wrong")

    def test_correct_password_opens(self, protected_pdf):
        with PDFSecurityManager.open_for_viewer(str(protected_pdf), password="user") as doc:
            assert doc.encrypted and "Plain content" in doc[0].text()


def test_encrypted_file_needs_a_password(protected_pdf):
    with pytest.raises(PasswordError):
        Document.open(protected_pdf)
