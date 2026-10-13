"""Tests for knowledge/chunk.py"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from chunk import _split_by_headings, _split_by_size, chunk_text, load_chunks, write_chunks
from schema import DocumentType, Jurisdiction


# ── _split_by_headings ────────────────────────────────────────────────────────

def test_split_by_headings_markdown():
    text = "# Section One\nFirst content.\n\n## Subsection\nSub content.\n\n# Section Two\nSecond content."
    sections = _split_by_headings(text)
    assert len(sections) >= 2
    headings_seen = [s[0] for s in sections]
    assert any("Section One" in " ".join(h) for h in headings_seen)


def test_split_no_headings():
    text = "Just a plain paragraph.\n\nAnother paragraph."
    sections = _split_by_headings(text)
    # Should return at least the full text as one section
    assert len(sections) >= 1
    all_text = " ".join(s[1] for s in sections)
    assert "plain paragraph" in all_text


def test_split_heading_path_breadcrumb():
    text = "# Chapter 1\nIntro.\n\n## Section 1.1\nContent."
    sections = _split_by_headings(text)
    # Find the deepest section
    deep = [s for s in sections if len(s[0]) >= 2]
    if deep:
        assert "Chapter 1" in deep[0][0]
        assert "Section 1.1" in deep[0][0]


# ── _split_by_size ────────────────────────────────────────────────────────────

def test_split_by_size_short_text():
    text = "Short fictional content. Nothing to split here."
    chunks = _split_by_size(text, target=500, overlap=50)
    assert len(chunks) == 1
    assert "Short fictional" in chunks[0]


def test_split_by_size_long_text():
    # Generate text longer than target
    para = "Fictional guidance paragraph. " * 20  # ~600 chars
    text = "\n\n".join([para] * 5)  # ~3000 chars
    chunks = _split_by_size(text, target=800, overlap=100)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 900  # some slack for overlap


def test_split_by_size_overlap():
    # Overlap should carry text from the end of one chunk to start of next
    para = "A" * 300
    text = "\n\n".join([para, para, para])
    chunks = _split_by_size(text, target=500, overlap=100)
    if len(chunks) > 1:
        # End of first chunk should appear in start of second
        end_of_first = chunks[0][-80:]
        start_of_second = chunks[1][:200]
        assert any(c in start_of_second for c in end_of_first.split() if c.strip())


def test_split_by_size_single_huge_paragraph():
    text = "X" * 2000
    chunks = _split_by_size(text, target=500, overlap=50)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk) <= 550  # target + some tolerance


# ── chunk_text ────────────────────────────────────────────────────────────────

def test_chunk_text_basic():
    text = (
        "# Fictional Guidance\n\n"
        "This is fictional content about an ASB procedure. " * 10
    )
    chunks = chunk_text(
        text=text,
        source_file="fictional_guidance.txt",
        source_hash="abcdef1234567890" * 4,
        target=500,
        overlap=50,
    )
    assert len(chunks) >= 1
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i
        assert chunk.source_file == "fictional_guidance.txt"
        assert chunk.document_type == DocumentType.OTHER
        assert chunk.jurisdiction == Jurisdiction.UNKNOWN
        assert chunk.text.strip() != ""
        assert chunk.chunk_id.startswith("abcdef12-")


def test_chunk_text_heading_path_populated():
    text = "# Enforcement Tools\n\nContent about fictional enforcement.\n"
    chunks = chunk_text(text, "doc.txt", "a" * 64, target=500, overlap=50)
    headed = [c for c in chunks if c.heading_path]
    assert len(headed) >= 1
    assert "Enforcement Tools" in headed[0].heading_path


def test_chunk_text_empty_text():
    chunks = chunk_text("", "empty.txt", "0" * 64)
    assert chunks == []


def test_chunk_text_ids_unique():
    text = "Fictional content. " * 100
    chunks = chunk_text(text, "doc.txt", "b" * 64, target=200, overlap=20)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


# ── write_chunks / load_chunks round-trip ────────────────────────────────────

def test_write_load_roundtrip(tmp_path):
    text = "# Fictional Section\n\nFictional ASB guidance content. " * 5
    chunks = chunk_text(text, "round_trip.txt", "c" * 64, target=300, overlap=30)
    out = tmp_path / "round_trip.jsonl"
    write_chunks(chunks, out)

    loaded = load_chunks(out)
    assert len(loaded) == len(chunks)
    for orig, loaded_chunk in zip(chunks, loaded):
        assert orig.chunk_id == loaded_chunk.chunk_id
        assert orig.text == loaded_chunk.text
        assert orig.chunk_index == loaded_chunk.chunk_index
        assert orig.heading_path == loaded_chunk.heading_path
