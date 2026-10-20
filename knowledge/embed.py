"""
knowledge/embed.py
Embedding and vector-store interfaces.

Usage (PowerShell):
    python knowledge/embed.py --source data/processed/chunks --db postgresql://...

What it does:
  - Reads .jsonl chunk files produced by chunk.py
  - Generates embeddings via a local Ollama model (default: nomic-embed-text)
  - Inserts into a pgvector table (requires the SQL migration to have been run)

IMPORTANT: Only OllamaEmbedProvider is wired in. No paid API is called.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from config import (
    DATA_PROCESSED,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_MODEL,
)
from chunk import load_chunks
from schema import ChunkMetadata


# ── Embedding provider interface ──────────────────────────────────────────────

class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def dimension(self) -> Optional[int]:
        ...

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts and return a list of float vectors."""
        ...


# ── Ollama provider ───────────────────────────────────────────────────────────

class OllamaEmbedProvider(EmbeddingProvider):
    """
    Embeds text locally using an Ollama model.
    Requires: ollama pull nomic-embed-text  (or whichever model is configured).
    """

    _DIMENSION_MAP = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
    }

    def __init__(
        self,
        model: str = OLLAMA_EMBED_MODEL,
        base_url: str = OLLAMA_BASE_URL,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> Optional[int]:
        return self._DIMENSION_MAP.get(self._model)

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        payload = json.dumps(
            {"model": self._model, "input": texts}
        ).encode()
        req = urllib.request.Request(
            f"{self._base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
            return body["embeddings"]
        except Exception as exc:
            raise RuntimeError(
                f"Ollama embed request failed: {exc}\n"
                f"  Is Ollama running? Try: ollama serve\n"
                f"  Is the model available? Try: ollama pull {self._model}"
            ) from exc


# ── Paid-provider stub ────────────────────────────────────────────────────────

class PaidEmbedProviderStub(EmbeddingProvider):
    """
    Placeholder that raises immediately, ensuring no API key is ever needed
    and no data is sent externally by accident.
    """

    @property
    def model_name(self) -> str:
        return "stub"

    @property
    def dimension(self) -> Optional[int]:
        return None

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError(
            "PaidEmbedProviderStub is intentionally non-functional. "
            "Use OllamaEmbedProvider for local embedding."
        )


# ── Vector store insertion ────────────────────────────────────────────────────

def insert_chunks(
    chunks: List[ChunkMetadata],
    vectors: List[List[float]],
    conn_string: str,
) -> int:
    """
    Insert chunks + vectors into the knowledge_chunks pgvector table.
    Returns the number of rows inserted.
    """
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # type: ignore
    except ImportError:
        raise RuntimeError(
            "psycopg2 not installed — run: pip install psycopg2-binary"
        )

    rows = [
        (
            chunk.chunk_id,
            chunk.source_file,
            chunk.source_hash,
            chunk.document_type.value,
            json.dumps(chunk.topic_tags),
            chunk.jurisdiction.value,
            chunk.document_date,
            json.dumps(chunk.heading_path),
            chunk.chunk_index,
            chunk.text,
            chunk.embed_model,
            chunk.embed_dimension,
            chunk.reviewed_by_owner,
            chunk.created_at,
            vector,
        )
        for chunk, vector in zip(chunks, vectors)
    ]

    with psycopg2.connect(conn_string) as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO knowledge_chunks (
                    chunk_id, source_file, source_hash, document_type,
                    topic_tags, jurisdiction, document_date, heading_path,
                    chunk_index, text, embed_model, embed_dimension,
                    reviewed_by_owner, created_at, embedding
                ) VALUES %s
                ON CONFLICT (chunk_id) DO UPDATE SET
                    text            = EXCLUDED.text,
                    embedding       = EXCLUDED.embedding,
                    embed_model     = EXCLUDED.embed_model,
                    embed_dimension = EXCLUDED.embed_dimension
                """,
                rows,
            )
        conn.commit()
    return len(rows)


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve(
    query: str,
    provider: EmbeddingProvider,
    conn_string: str,
    k: int = 5,
    jurisdiction_filter: Optional[str] = None,
) -> List[dict]:
    """
    Embed `query`, run a cosine-similarity search, return top-k rows.
    Optionally filter by jurisdiction (e.g. 'Wales').
    """
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # type: ignore
    except ImportError:
        raise RuntimeError("psycopg2 not installed — run: pip install psycopg2-binary")

    vector = provider.embed([query])[0]

    with psycopg2.connect(conn_string) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if jurisdiction_filter:
                cur.execute(
                    """
                    SELECT chunk_id, source_file, document_type, jurisdiction,
                           heading_path, chunk_index, text,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM knowledge_chunks
                    WHERE jurisdiction = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (str(vector), jurisdiction_filter, str(vector), k),
                )
            else:
                cur.execute(
                    """
                    SELECT chunk_id, source_file, document_type, jurisdiction,
                           heading_path, chunk_index, text,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM knowledge_chunks
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (str(vector), str(vector), k),
                )
            return [dict(row) for row in cur.fetchall()]


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed chunks and insert into pgvector."
    )
    parser.add_argument(
        "--source", type=Path, default=DATA_PROCESSED / "chunks",
        help="Folder containing .jsonl chunk files",
    )
    parser.add_argument(
        "--db", required=True,
        help="PostgreSQL connection string (postgresql://user:pass@host/db)",
    )
    parser.add_argument(
        "--batch", type=int, default=32,
        help="Batch size for embedding requests (default: 32)",
    )
    parser.add_argument(
        "--model", default=OLLAMA_EMBED_MODEL,
        help=f"Ollama embedding model (default: {OLLAMA_EMBED_MODEL})",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Chunks folder does not exist: {args.source}")
        sys.exit(1)

    jsonl_files = sorted(args.source.glob("*.jsonl"))
    if not jsonl_files:
        print(f"No .jsonl files found in {args.source}")
        return

    provider = OllamaEmbedProvider(model=args.model)
    total_inserted = 0

    for path in jsonl_files:
        chunks = load_chunks(path)
        if not chunks:
            continue

        unreviewed = [c for c in chunks if not c.reviewed_by_owner]
        if unreviewed:
            print(
                f"  WARN  {path.name}: {len(unreviewed)} chunk(s) not reviewed. "
                "Set reviewed_by_owner=True after checking scrub reports."
            )
            continue

        print(f"  EMBED {path.name}  ({len(chunks)} chunks)…")
        vectors: List[List[float]] = []
        for i in range(0, len(chunks), args.batch):
            batch = chunks[i:i + args.batch]
            texts = [c.text for c in batch]
            vecs = provider.embed(texts)
            vectors.extend(vecs)
            time.sleep(0.1)  # be gentle with local Ollama

        # Stamp embed provenance back onto chunks
        for chunk, vec in zip(chunks, vectors):
            chunk.embed_model = provider.model_name
            chunk.embed_dimension = len(vec)

        n = insert_chunks(chunks, vectors, args.db)
        print(f"        → {n} row(s) inserted/updated")
        total_inserted += n

    print(f"\nDone: {total_inserted} total row(s) inserted/updated.")


if __name__ == "__main__":
    main()
