"""Tests for knowledge/inventory.py"""
import csv
import hashlib
import sys
from pathlib import Path

import pytest

# Make the knowledge package importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from inventory import jaccard, scan_folder, sha256_file, write_csv


# ── sha256_file ───────────────────────────────────────────────────────────────

def test_sha256_file(tmp_path):
    p = tmp_path / "example.txt"
    p.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert sha256_file(p) == expected


def test_sha256_file_empty(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_bytes(b"")
    result = sha256_file(p)
    assert len(result) == 64  # valid hex digest


# ── jaccard ───────────────────────────────────────────────────────────────────

def test_jaccard_identical():
    assert jaccard("hello world", "hello world") == 1.0


def test_jaccard_completely_different():
    score = jaccard("abcdefgh", "uvwxyz12")
    assert score < 0.1


def test_jaccard_empty_strings():
    assert jaccard("", "") == 0.0
    assert jaccard("hello", "") == 0.0
    assert jaccard("", "hello") == 0.0


def test_jaccard_partial_overlap():
    score = jaccard("the quick brown fox", "the quick red fox")
    assert 0.0 < score < 1.0


# ── scan_folder ───────────────────────────────────────────────────────────────

def test_scan_folder_basic(tmp_path):
    (tmp_path / "example.txt").write_text(
        "This is a fictional test document about Resident A at Flat 1 Example Court.",
        encoding="utf-8",
    )
    rows = scan_folder(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["filename"] == "example.txt"
    assert row["extension"] == ".txt"
    assert row["exact_duplicate_of"] == ""


def test_scan_folder_exact_duplicates(tmp_path):
    content = b"Identical fictional content for duplicate test."
    (tmp_path / "file_a.txt").write_bytes(content)
    (tmp_path / "file_b.txt").write_bytes(content)

    rows = scan_folder(tmp_path)
    assert len(rows) == 2

    duplicates = [r for r in rows if r["exact_duplicate_of"]]
    assert len(duplicates) == 1
    assert duplicates[0]["exact_duplicate_of"] == "file_a.txt"


def test_scan_folder_ignores_unsupported(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    (tmp_path / "note.txt").write_text("fictional note", encoding="utf-8")
    rows = scan_folder(tmp_path)
    assert len(rows) == 1
    assert rows[0]["filename"] == "note.txt"


def test_scan_folder_empty(tmp_path, capsys):
    rows = scan_folder(tmp_path)
    assert rows == []
    captured = capsys.readouterr()
    assert "No supported files" in captured.out


def test_scan_folder_subdirectory(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "doc.md").write_text("# Fictional heading\nSome content.", encoding="utf-8")
    rows = scan_folder(tmp_path)
    assert len(rows) == 1
    assert "subdir" in rows[0]["relative_path"]


# ── write_csv ─────────────────────────────────────────────────────────────────

def test_write_csv(tmp_path):
    rows = [
        {
            "filename": "example.txt",
            "relative_path": "example.txt",
            "extension": ".txt",
            "size_bytes": 42,
            "pages": "",
            "word_count": 10,
            "sha256": "abc123",
            "exact_duplicate_of": "",
            "near_duplicate_of": "",
            "extraction_error": "",
        }
    ]
    out = tmp_path / "out.csv"
    write_csv(rows, out)

    assert out.exists()
    with out.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert len(data) == 1
    assert data[0]["filename"] == "example.txt"


def test_write_csv_creates_parent(tmp_path):
    rows = []
    out = tmp_path / "nested" / "dir" / "out.csv"
    write_csv(rows, out)
    assert out.exists()
