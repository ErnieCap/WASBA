"""
knowledge/chunk.py
Chunking module — structure-first (headings), then size-based with overlap.

Usage (PowerShell):
    python knowledge/chunk.py --source data/processed/scrubbed --out data/processed/chunks

Strategy:
  1. Split on markdown-style headings (# / ## / ###) or ALL-CAPS section titles
  2. If a section exceeds CHUNK_TARGET_CHARS, split further on paragraph breaks
  3. Apply a fixed character overlap between adjacent chunks
  4. Each chunk is written as one JSON line (JSONL) including its metadata stub
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple

from config import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
    DATA_PROCESSED,
)
from schema import ChunkMetadata, DocumentType, Jurisdiction

# ── Heading detection ─────────────────────────────────────────────────────────

# Matches markdown headings (# Title) and ALL-CAPS section headers (3+ words
# or a single line in all-caps that looks like a heading, not a full sentence).
_HEADING_RE = re.compile(
    r"^(?:(#{1,6})\s+(.+)|([A-Z][A-Z0-9 \-:]{3,}[A-Z0-9]))$",
    re.MULTILINE,
)


def _split_by_headings(text: str) -> List[Tuple[List[str], str]]:
    """
    Return a list of (heading_path, section_text) pairs.
    heading_path is the breadcrumb of headings up to and including the section.
    """
    sections: List[Tuple[List[str], str]] = []
    last_end = 0
    current_path: List[str] = []
    current_level: int = 0

    for m in _HEADING_RE.finditer(text):
        # Flush text before this heading
        body = text[last_end:m.start()].strip()
        if body and current_path:
            sections.append((list(current_path), body))
        elif body:
            # Text before any heading — treat as preamble
            sections.append(([], body))

        if m.group(1):  # markdown heading
            level = len(m.group(1))
            title = m.group(2).strip()
        else:  # ALL-CAPS title
            level = 1
            title = m.group(3).strip()

        # Update breadcrumb
        if level <= current_level:
            # Pop back to the right depth
            current_path = current_path[:level - 1]
        current_path.append(title)
        current_level = level
        last_end = m.end()

    # Flush remaining text
    remainder = text[last_end:].strip()
    if remainder:
        sections.append((list(current_path), remainder))

    return sections


# ── Size-based splitting ──────────────────────────────────────────────────────

def _split_by_size(
    text: str,
    target: int = CHUNK_TARGET_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> List[str]:
    """
    Split text into chunks of at most `target` chars with `overlap` chars
    of context from the previous chunk. Splits on paragraph boundaries where
    possible; falls back to hard splits if a paragraph exceeds the target.
    """
    paragraphs = re.split(r"\n{2,}", text)
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 <= target:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
                # Start next chunk with overlap from end of current
                overlap_text = current[-overlap:] if len(current) > overlap else current
                current = (overlap_text + "\n\n" + para).strip()
            else:
                # Single paragraph exceeds target — hard split
                start = 0
                while start < len(para):
                    end = start + target
                    chunk = para[start:end]
                    chunks.append(chunk)
                    start = end - overlap

    if current:
        chunks.append(current)

    return chunks


# ── Public API ────────────────────────────────────────────────────────────────

def chunk_text(
    text: str,
    source_file: str,
    source_hash: str,
    target: int = CHUNK_TARGET_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> List[ChunkMetadata]:
    """
    Produce a list of ChunkMetadata objects from a scrubbed text document.
    Caller should update document_type, topic_tags, jurisdiction, document_date,
    and set reviewed_by_owner = True after manual review.
    """
    sections = _split_by_headings(text)
    chunks: List[ChunkMetadata] = []
    index = 0

    for heading_path, section_text in sections:
        sub_chunks = _split_by_size(section_text, target, overlap)
        for sub in sub_chunks:
            if not sub.strip():
                continue
            chunk_id = f"{source_hash[:8]}-{index}"
            chunks.append(
                ChunkMetadata(
                    chunk_id=chunk_id,
                    source_file=source_file,
                    source_hash=source_hash,
                    document_type=DocumentType.OTHER,
                    topic_tags=[],
                    jurisdiction=Jurisdiction.UNKNOWN,
                    heading_path=heading_path,
                    chunk_index=index,
                    text=sub,
                )
            )
            index += 1

    return chunks


# ── I/O ───────────────────────────────────────────────────────────────────────

def write_chunks(chunks: List[ChunkMetadata], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk.model_dump_json() + "\n")


def load_chunks(path: Path) -> List[ChunkMetadata]:
    chunks = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(ChunkMetadata.model_validate_json(line))
    return chunks


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import hashlib

    parser = argparse.ArgumentParser(
        description="Chunk scrubbed text files into overlapping segments."
    )
    parser.add_argument(
        "--source", type=Path, default=DATA_PROCESSED / "scrubbed",
        help="Folder of scrubbed .txt files",
    )
    parser.add_argument(
        "--out", type=Path, default=DATA_PROCESSED / "chunks",
        help="Output folder for .jsonl chunk files",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Source folder does not exist: {args.source}")
        sys.exit(1)

    txt_files = sorted(args.source.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files found in {args.source}")
        return

    total_chunks = 0
    for path in txt_files:
        text = path.read_text(encoding="utf-8")
        source_hash = hashlib.sha256(text.encode()).hexdigest()
        chunks = chunk_text(text, path.name, source_hash)
        out_path = args.out / (path.stem + ".jsonl")
        write_chunks(chunks, out_path)
        print(f"  {path.name}  →  {len(chunks)} chunk(s)  →  {out_path.name}")
        total_chunks += len(chunks)

    print(f"\nDone: {total_chunks} total chunk(s) across {len(txt_files)} file(s).")


if __name__ == "__main__":
    main()
