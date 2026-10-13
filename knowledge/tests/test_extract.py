"""Tests for knowledge/extract.py"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from extract import clean_text, extract_text, process_file


# ── clean_text ────────────────────────────────────────────────────────────────

def test_clean_text_normalises_whitespace():
    raw = "Hello   world\n\n\n\nNew paragraph"
    result = clean_text(raw)
    assert "   " not in result
    # Three blank lines collapsed to one
    assert "\n\n\n" not in result


def test_clean_text_strips_control_chars():
    raw = "Normal text\x00with null\x01bytes"
    result = clean_text(raw)
    assert "\x00" not in result
    assert "\x01" not in result


def test_clean_text_preserves_newlines():
    raw = "Line one\nLine two"
    result = clean_text(raw)
    assert "Line one" in result
    assert "Line two" in result


def test_clean_text_strips_edges():
    raw = "\n\n  Hello world  \n\n"
    result = clean_text(raw)
    assert result == "Hello world"


def test_clean_text_empty():
    assert clean_text("") == ""
    assert clean_text("   \n\n  ") == ""


def test_clean_text_unicode_normalise():
    # Decomposed é should become composed é
    raw = "café"  # e + combining acute
    result = clean_text(raw)
    assert result == "café"  # precomposed é


# ── extract_text ──────────────────────────────────────────────────────────────

def test_extract_txt_file(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("Fictional case note for Resident A.", encoding="utf-8")
    text, error = extract_text(p)
    assert error is None
    assert "Resident A" in text


def test_extract_md_file(tmp_path):
    p = tmp_path / "guide.md"
    p.write_text("# Fictional Guidance\nSome content.", encoding="utf-8")
    text, error = extract_text(p)
    assert error is None
    assert "Fictional Guidance" in text


def test_extract_rtf_file(tmp_path):
    p = tmp_path / "note.rtf"
    p.write_text("Fictional RTF content", encoding="utf-8")
    text, error = extract_text(p)
    assert error is None


def test_extract_unsupported_type(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("a,b,c")
    text, error = extract_text(p)
    assert text == ""
    assert "unsupported" in (error or "").lower()


def test_extract_pdf_missing_pdfplumber(tmp_path, monkeypatch):
    """Should return an error message if pdfplumber is not installed."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pdfplumber":
            raise ImportError("mocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4")
    text, error = extract_text(p)
    assert text == ""
    assert error is not None
    assert "pdfplumber" in error


def test_extract_docx_missing_python_docx(tmp_path, monkeypatch):
    """Should return an error message if python-docx is not installed."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "docx":
            raise ImportError("mocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    p = tmp_path / "doc.docx"
    p.write_bytes(b"PK fake docx")
    text, error = extract_text(p)
    assert text == ""
    assert error is not None
    assert "python-docx" in error


# ── process_file ──────────────────────────────────────────────────────────────

def test_process_file_creates_output(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    out = tmp_path / "out"
    (src / "note.txt").write_text("Fictional note content.", encoding="utf-8")

    success, error = process_file(src / "note.txt", out)
    assert success
    assert error is None
    assert (out / "note.txt").exists()
    assert "Fictional" in (out / "note.txt").read_text()


def test_process_file_skip_existing(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (src / "note.txt").write_text("Fictional.", encoding="utf-8")
    (out / "note.txt").write_text("old content")

    success, error = process_file(src / "note.txt", out, force=False)
    assert success
    # Original should not be overwritten
    assert (out / "note.txt").read_text() == "old content"


def test_process_file_force_overwrites(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (src / "note.txt").write_text("New fictional content.", encoding="utf-8")
    (out / "note.txt").write_text("old content")

    success, error = process_file(src / "note.txt", out, force=True)
    assert success
    assert "New fictional" in (out / "note.txt").read_text()
