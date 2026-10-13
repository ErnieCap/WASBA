-- knowledge/migrations/001_knowledge_chunks.sql
-- Creates the pgvector table for knowledge chunks.
--
-- Prerequisites:
--   1. PostgreSQL with the pgvector extension available
--      (Render Postgres includes it; local: CREATE EXTENSION IF NOT EXISTS vector)
--   2. Run ONCE on your target database — DO NOT run on production until you
--      have verified the pipeline end-to-end on a local copy.
--
-- PowerShell:
--   psql $env:DATABASE_URL -f knowledge/migrations/001_knowledge_chunks.sql
--
-- NOTE: This migration is NOT executed automatically by the application.
-- Run it manually when you are ready to start storing embeddings.

-- Enable the pgvector extension (safe to run if already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- Main table
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id               BIGSERIAL PRIMARY KEY,
    chunk_id         TEXT        NOT NULL UNIQUE,   -- <hash[:8]>-<index>
    source_file      TEXT        NOT NULL,
    source_hash      TEXT        NOT NULL,
    document_type    TEXT        NOT NULL DEFAULT 'other',
    topic_tags       JSONB       NOT NULL DEFAULT '[]',
    jurisdiction     TEXT        NOT NULL DEFAULT 'unknown',
    document_date    TEXT,                           -- ISO year / date / range
    heading_path     JSONB       NOT NULL DEFAULT '[]',
    chunk_index      INTEGER     NOT NULL,
    text             TEXT        NOT NULL,
    embed_model      TEXT,
    embed_dimension  INTEGER,
    reviewed_by_owner BOOLEAN    NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 768 dims for nomic-embed-text; change if you switch models
    -- (you will need to drop and recreate the column and index if you do)
    embedding        vector(768)
);

-- IVFFlat approximate nearest-neighbour index for cosine similarity.
-- Build this AFTER you have inserted a reasonable number of rows (>= 1000).
-- If the table is empty the index builds in seconds but provides no benefit.
-- Adjust lists = round(sqrt(row_count)) as your corpus grows.
CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
    ON knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- Handy index for jurisdiction filtering
CREATE INDEX IF NOT EXISTS knowledge_chunks_jurisdiction_idx
    ON knowledge_chunks (jurisdiction);

-- Handy index for source file lookups
CREATE INDEX IF NOT EXISTS knowledge_chunks_source_file_idx
    ON knowledge_chunks (source_file);

COMMENT ON TABLE knowledge_chunks IS
    'Knowledge base chunks for the asbguide.com vector search feature. '
    'Populated by knowledge/embed.py. Never stores un-scrubbed personal data.';
