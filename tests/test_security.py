"""Tests for `pdf_security.security` — protects against regression of 5 bugs.

Each TestBugFix* class corresponds to one specific bug we fixed and includes
the roundtrip (encrypt → unlock / check / strip) that would have caught the
original issue.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdf_security import (
    PDFFileError,
    PDFInvalidPasswordError,
    PDFOwnerRequiredError,
    PDFPasswordRequiredError,
    PDFSecurityManager,
)


# ─────────────────────────────────────────────────────────────────── helpers


@pytest.fixture
def plain_pdf(tmp_path: Path) -> Path:
    """An unencrypted 1-page PDF."""
    path = tmp_path / "plain.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Plain content")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def protected_pdf(plain_pdf: Path, tmp_path: Path) -> Path:
    """Encrypt the plain PDF with user_pw='user', owner_pw='owner'."""
    out = tmp_path / "protected.pdf"
    PDFSecurityManager.protect_pdf(
        str(plain_pdf), str(out),
        user_password="user",
        owner_password="owner",
        permissions=PDFSecurityManager.PDF_PERM_PRINT,
    )
    return out


@pytest.fixture
def owner_only_pdf(plain_pdf: Path, tmp_path: Path) -> Path:
    """PDF with ONLY an owner password — openable without auth, but restricted."""
    out = tmp_path / "owner_only.pdf"
    PDFSecurityManager.protect_pdf(
        str(plain_pdf), str(out),
        user_password="",
        owner_password="owner",
        permissions=PDFSecurityManager.PDF_PERM_PRINT,
    )
    return out


def _is_actually_encrypted(path: Path) -> bool:
    """Open a PDF fresh and report whether the file on disk is encrypted."""
    d = fitz.open(str(path))
    try:
        return bool(d.is_encrypted)
    finally:
        d.close()


# ───────────────────────────────────────────── BUG #1: unlock_pdf_to_file


class TestBugFix1_UnlockToFileActuallyUnlocks:
    """Previously `unlock_pdf_to_file` saved with PDF_ENCRYPT_KEEP → still encrypted."""

    def test_output_file_is_not_encrypted(self, protected_pdf, tmp_path):
        out = tmp_path / "unlocked.pdf"
        ok = PDFSecurityManager.unlock_pdf_to_file(
            str(protected_pdf), "user", str(out),
        )
        assert ok is True
        assert out.exists()
        # The whole point of this function: output must be unencrypted
        assert _is_actually_encrypted(out) is False

    def test_content_survives_unlock(self, protected_pdf, tmp_path):
        out = tmp_path / "unlocked.pdf"
        PDFSecurityManager.unlock_pdf_to_file(str(protected_pdf), "user", str(out))
        d = fitz.open(str(out))
        try:
            assert "Plain content" in d[0].get_text()
        finally:
            d.close()

    def test_wrong_password_raises_invalid(self, protected_pdf, tmp_path):
        out = tmp_path / "unlocked.pdf"
        with pytest.raises(PDFInvalidPasswordError):
            PDFSecurityManager.unlock_pdf_to_file(str(protected_pdf), "wrong", str(out))


# ───────────────────────────────────────── BUG #2: change_pdf_permissions / None


class TestBugFix2_ChangePermissionsRejectsNone:
    """Previously, None passwords were treated as '' → silently stripped protection."""

    def test_none_user_password_raises(self, protected_pdf, tmp_path):
        out = tmp_path / "out.pdf"
        with pytest.raises(ValueError, match="no pueden ser None"):
            PDFSecurityManager.change_pdf_permissions(
                str(protected_pdf), str(out),
                current_owner_password="owner",
                new_user_password=None,           # ← used to silently work
                new_owner_password="owner",
            )

    def test_none_owner_password_raises(self, protected_pdf, tmp_path):
        out = tmp_path / "out.pdf"
        with pytest.raises(ValueError, match="no pueden ser None"):
            PDFSecurityManager.change_pdf_permissions(
                str(protected_pdf), str(out),
                current_owner_password="owner",
                new_user_password="x",
                new_owner_password=None,           # ← used to silently work
            )

    def test_explicit_empty_string_is_allowed(self, protected_pdf, tmp_path):
        """User must opt in explicitly to '' if they want to drop a password layer."""
        out = tmp_path / "out.pdf"
        ok = PDFSecurityManager.change_pdf_permissions(
            str(protected_pdf), str(out),
            current_owner_password="owner",
            new_user_password="",          # explicit — dropping user pw
            new_owner_password="newowner", # keeping/changing owner pw
            permissions=PDFSecurityManager.PDF_PERM_PRINT,
        )
        assert ok is True


# ───────────────────────────────────────── BUG #3: remove_protection owner check


class TestBugFix3_RemoveProtectionRequiresOwnerAuth:
    """Previously, passing the user pw as 'owner_password' authed at level 1 and proceeded."""

    def test_user_password_as_owner_is_rejected(self, protected_pdf, tmp_path):
        out = tmp_path / "out.pdf"
        with pytest.raises(PDFOwnerRequiredError):
            PDFSecurityManager.remove_protection(
                str(protected_pdf), str(out),
                owner_password="user",      # ← user pw, NOT owner pw → must reject
            )

    def test_invalid_password_raises_invalid(self, protected_pdf, tmp_path):
        out = tmp_path / "out.pdf"
        with pytest.raises(PDFInvalidPasswordError):
            PDFSecurityManager.remove_protection(
                str(protected_pdf), str(out),
                owner_password="totally_wrong",
            )

    def test_owner_password_succeeds(self, protected_pdf, tmp_path):
        out = tmp_path / "out.pdf"
        ok = PDFSecurityManager.remove_protection(
            str(protected_pdf), str(out),
            owner_password="owner",
        )
        assert ok is True
        assert _is_actually_encrypted(out) is False

    def test_already_unprotected_passes_through(self, plain_pdf, tmp_path):
        """Unencrypted input shouldn't raise — just copy."""
        out = tmp_path / "out.pdf"
        ok = PDFSecurityManager.remove_protection(
            str(plain_pdf), str(out),
            owner_password="anything",
        )
        assert ok is True
        assert out.exists()


# ─────────────────────────────────────────────── BUG #4: is_protected error propagation


class TestBugFix4_IsProtectedPropagatesErrors:
    """Previously, ANY exception became `return False`, masking real failures."""

    def test_nonexistent_file_raises(self, tmp_path):
        ghost = tmp_path / "does_not_exist.pdf"
        # Used to silently return False; now must surface the real error.
        with pytest.raises(PDFFileError):
            PDFSecurityManager.is_protected(str(ghost))

    def test_non_pdf_file_raises(self, tmp_path):
        garbage = tmp_path / "not_a_pdf.pdf"
        garbage.write_bytes(b"this is plain text, not a PDF")
        with pytest.raises(PDFFileError):
            PDFSecurityManager.is_protected(str(garbage))

    def test_real_pdf_unprotected_returns_false(self, plain_pdf):
        assert PDFSecurityManager.is_protected(str(plain_pdf)) is False

    def test_real_pdf_protected_returns_true(self, protected_pdf):
        assert PDFSecurityManager.is_protected(str(protected_pdf)) is True


# ─────────────────────────────────────── BUG #5: PDFSecurityInfo password flags


class TestBugFix5_HonestPasswordFlags:
    """Previously, has_user_password and has_owner_password both echoed is_encrypted."""

    def test_unprotected_has_no_passwords(self, plain_pdf):
        info = PDFSecurityManager.get_security_info(str(plain_pdf))
        assert info.is_encrypted is False
        assert info.has_user_password is False
        assert info.has_owner_password is False

    def test_fully_protected_has_user_password(self, protected_pdf):
        info = PDFSecurityManager.get_security_info(str(protected_pdf))
        assert info.is_encrypted is True
        assert info.has_user_password is True
        assert info.has_owner_password is True

    def test_owner_only_does_not_claim_user_password(self, owner_only_pdf):
        """
        Owner-only protected PDFs were the regression case: they're openable
        without password (just restricted), but the old code claimed
        has_user_password=True. Test that we now report it honestly.
        """
        info = PDFSecurityManager.get_security_info(str(owner_only_pdf))
        assert info.is_encrypted is True
        assert info.has_user_password is False    # ← the fix
        assert info.has_owner_password is True


# ────────────────────────────────────────────────────── Exception hierarchy


class TestExceptionHierarchy:
    """Ensure callers can catch broadly via PDFSecurityError or specifically."""

    def test_password_required_inherits_security_error(self):
        from pdf_security import PDFSecurityError
        assert issubclass(PDFPasswordRequiredError, PDFSecurityError)

    def test_invalid_password_inherits_security_error(self):
        from pdf_security import PDFSecurityError
        assert issubclass(PDFInvalidPasswordError, PDFSecurityError)

    def test_owner_required_inherits_security_error(self):
        from pdf_security import PDFSecurityError
        assert issubclass(PDFOwnerRequiredError, PDFSecurityError)

    def test_file_error_inherits_security_error(self):
        from pdf_security import PDFSecurityError
        assert issubclass(PDFFileError, PDFSecurityError)


# ────────────────────────────────────────────────────────── open_for_viewer


class TestOpenForViewer:
    """The viewer-side path used by the main app to open PDFs."""

    def test_plain_pdf_opens_directly(self, plain_pdf):
        doc = PDFSecurityManager.open_for_viewer(str(plain_pdf))
        try:
            assert doc.page_count == 1
        finally:
            doc.close()

    def test_encrypted_without_password_raises_required(self, protected_pdf):
        with pytest.raises(PDFPasswordRequiredError):
            PDFSecurityManager.open_for_viewer(str(protected_pdf))

    def test_encrypted_with_wrong_password_raises_invalid(self, protected_pdf):
        with pytest.raises(PDFInvalidPasswordError):
            PDFSecurityManager.open_for_viewer(str(protected_pdf), password="wrong")

    def test_encrypted_with_correct_password_opens(self, protected_pdf):
        doc = PDFSecurityManager.open_for_viewer(str(protected_pdf), password="user")
        try:
            assert doc.page_count == 1
            assert doc.is_encrypted    # the FILE is encrypted, but we're authenticated
        finally:
            doc.close()


# ─────────────────────────────────────────────────────── can_save_changes


class TestCanSaveChanges:
    def test_plain_pdf_can_be_saved(self, plain_pdf):
        doc = fitz.open(str(plain_pdf))
        try:
            assert PDFSecurityManager.can_save_changes(doc) is True
        finally:
            doc.close()

    def test_protected_pdf_respects_permissions(self, protected_pdf):
        """Our fixture grants PDF_PERM_PRINT only — no modify/annotate/forms."""
        doc = fitz.open(str(protected_pdf))
        try:
            doc.authenticate("user")    # user-level auth → restricted permissions
            assert PDFSecurityManager.can_save_changes(doc) is False
        finally:
            doc.close()
