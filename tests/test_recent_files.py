"""Tests for `recent_files` — persistent MRU list shown on Home.

Critical behaviors:
  · Persists across runs (JSON file in $HOME)
  · Dedupes (re-pushing an existing path moves it to front, not duplicates)
  · Caps at _MAX
  · Filters out paths that no longer exist on disk
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import recent_files as rf


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch):
    """Redirect rf._STORE to a temp file so tests don't touch the user's HOME."""
    store = tmp_path / ".extraer_pdfs_recent.json"
    monkeypatch.setattr(rf, "_STORE", store)
    return store


def _make_pdf(tmp_path: Path, name: str) -> str:
    """Create a placeholder file that recent_files.load() will accept as existing."""
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4\n%fake\n")
    return str(p)


class TestRecentFiles:
    def test_load_returns_empty_when_no_file(self, isolated_store):
        assert rf.load() == []

    def test_push_then_load(self, isolated_store, tmp_path):
        p = _make_pdf(tmp_path, "a.pdf")
        rf.push(p)
        assert rf.load() == [p]

    def test_load_returns_most_recent_first(self, isolated_store, tmp_path):
        p1 = _make_pdf(tmp_path, "first.pdf")
        p2 = _make_pdf(tmp_path, "second.pdf")
        rf.push(p1)
        rf.push(p2)
        assert rf.load() == [p2, p1]

    def test_push_dedupes_existing_path(self, isolated_store, tmp_path):
        """Re-pushing an existing path moves it to the front; no duplicates."""
        p1 = _make_pdf(tmp_path, "a.pdf")
        p2 = _make_pdf(tmp_path, "b.pdf")
        rf.push(p1)
        rf.push(p2)
        rf.push(p1)   # promote p1 back to front
        loaded = rf.load()
        assert loaded == [p1, p2]
        assert loaded.count(p1) == 1   # only one entry

    def test_push_enforces_max_cap(self, isolated_store, tmp_path):
        """Pushing beyond _MAX trims the oldest entries."""
        for i in range(rf._MAX + 5):
            rf.push(_make_pdf(tmp_path, f"f{i}.pdf"))
        assert len(rf.load()) == rf._MAX

    def test_load_filters_out_nonexistent_paths(self, isolated_store, tmp_path):
        """If a file in the JSON was deleted/moved, load() omits it."""
        good = _make_pdf(tmp_path, "exists.pdf")
        ghost = str(tmp_path / "moved.pdf")  # never created
        # Write the store directly with both entries
        isolated_store.write_text(json.dumps([ghost, good]), encoding="utf-8")
        loaded = rf.load()
        assert ghost not in loaded
        assert good in loaded

    def test_load_survives_corrupt_json(self, isolated_store):
        """A garbled JSON file should not crash load() — returns []."""
        isolated_store.write_text("{ this is not valid json", encoding="utf-8")
        assert rf.load() == []

    def test_load_survives_unexpected_shape(self, isolated_store):
        """If the JSON contains something other than a list, load() returns []."""
        isolated_store.write_text(json.dumps({"key": "value"}), encoding="utf-8")
        assert rf.load() == []

    def test_load_drops_non_string_entries(self, isolated_store, tmp_path):
        """Mixed-type list: only string paths to existing files survive."""
        good = _make_pdf(tmp_path, "g.pdf")
        isolated_store.write_text(
            json.dumps([good, 42, None, {"obj": 1}, ["nested"]]),
            encoding="utf-8",
        )
        assert rf.load() == [good]

    def test_push_is_persistent(self, isolated_store, tmp_path):
        """After push(), the JSON file exists with the pushed path."""
        p = _make_pdf(tmp_path, "x.pdf")
        rf.push(p)
        assert isolated_store.exists()
        data = json.loads(isolated_store.read_text(encoding="utf-8"))
        assert data == [p]
