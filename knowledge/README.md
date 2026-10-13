# Knowledge Pipeline

A local-only document pipeline for building the asbguide.com vector knowledge base.

**Data protection first.** Source documents, extracted text, embeddings and scrub reports are all git-ignored. None of this ever leaves your machine. No document text is sent to any external or remote service at any point.

---

## What's here

| File | What it does |
|------|-------------|
| `inventory.py` | Scan your documents folder, detect duplicates, write a CSV |
| `extract.py` | Pull text out of PDF, DOCX, TXT and MD files |
| `scrub.py` | Redact personal data (regex + spaCy NER + optional Ollama pass) |
| `chunk.py` | Split scrubbed text into overlapping chunks |
| `embed.py` | Embed chunks with a local Ollama model, insert into pgvector |
| `evaluate.py` | Score retrieval quality with 15 held-out questions |
| `config.py` | All settings in one place — edit this, not the scripts |
| `schema.py` | Pydantic models for chunk metadata and scrub reports |
| `tags.yaml` | Topic tag vocabulary — add or rename tags here |
| `migrations/001_knowledge_chunks.sql` | Run once to create the pgvector table |
| `eval/questions.jsonl` | 15 fictional evaluation questions |

---

## First-time setup (PowerShell)

```powershell
# 1. Create a virtual environment (do this once)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r knowledge/requirements.txt

# 3. Download the spaCy language model
python -m spacy download en_core_web_sm

# 4. Install and start Ollama  (https://ollama.com)
ollama pull nomic-embed-text
```

---

## Step-by-step pipeline

### 1. Put your documents in `data/raw/`

Drop PDF, DOCX, TXT or MD files into `data/raw/`. This folder is git-ignored.
Subdirectories are fine.

### 2. Run the inventory

```powershell
python knowledge/inventory.py
```

Opens `data/review/inventory.csv`. Check it in Excel before going further.
The inventory flags exact and near-duplicate files so you can decide which to keep.

### 3. Extract text

```powershell
python knowledge/extract.py
```

Writes one `.txt` per source file into `data/processed/`. Skips files already extracted. Use `--force` to re-extract.

### 4. Scrub personal data

```powershell
python knowledge/scrub.py
```

Writes scrubbed `.txt` files to `data/processed/scrubbed/` and a JSON report per file to `data/review/scrub_reports/`. Open each report and check the redactions before continuing.

The scrubber runs three passes:
- **Regex** — postcodes, phone numbers, NHS numbers, NI numbers, emails, dates, URLs, street addresses
- **spaCy NER** — person names, place names, organisation names
- **Ollama LLM** — optional catch-all pass (disabled by default)

To enable the Ollama LLM pass, set `SCRUB_OLLAMA_ENABLED = True` in `config.py`.

**After reviewing the reports**, set `reviewed_by_owner = True` on each chunk's metadata. Until you do this, `embed.py` will refuse to embed those chunks.

### 5. Chunk the scrubbed text

```powershell
python knowledge/chunk.py
```

Writes one `.jsonl` file per document to `data/processed/chunks/`. Each line is a chunk with its metadata stub.

Open a `.jsonl` file in a text editor and fill in the classification fields (`document_type`, `topic_tags`, `jurisdiction`, `document_date`) for each chunk. See `tags.yaml` for the available topic tags.

### 6. Run the SQL migration (once only)

```powershell
psql $env:DATABASE_URL -f knowledge/migrations/001_knowledge_chunks.sql
```

This creates the `knowledge_chunks` table and a cosine-similarity index. Run it once on your target database. It is safe to run again (uses `IF NOT EXISTS`).

### 7. Embed and store

```powershell
python knowledge/embed.py --db $env:DATABASE_URL
```

Reads chunk `.jsonl` files, embeds each chunk locally with Ollama (`nomic-embed-text` by default), and inserts into pgvector. Chunks without `reviewed_by_owner = True` are skipped with a warning.

### 8. Evaluate retrieval quality

```powershell
python knowledge/evaluate.py --db $env:DATABASE_URL
```

Embeds 15 held-out questions and checks whether the top-k results include a chunk tagged with an expected topic. Prints hit-rate-at-1, 3, 5 and 10.

---

## Configuration

All settings are in `knowledge/config.py`. Key values:

| Setting | Default | Notes |
|---------|---------|-------|
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Pull with `ollama pull nomic-embed-text` |
| `OLLAMA_CHAT_MODEL` | `llama3` | Used only if SCRUB_OLLAMA_ENABLED = True |
| `CHUNK_TARGET_CHARS` | `1800` | ~450 tokens at 4 chars/token |
| `CHUNK_OVERLAP_CHARS` | `200` | Context carried between adjacent chunks |
| `SCRUB_OLLAMA_ENABLED` | `False` | Set True for the extra LLM scrub pass |
| `SCRUB_SIMILARITY_THRESHOLD` | `0.80` | Jaccard threshold for near-duplicate detection |

---

## Welsh law note

The Renting Homes (Wales) Act 2016 replaced the assured tenancy regime for social housing in Wales. Tag Welsh-specific documents with `jurisdiction: Wales` in the chunk metadata (and use the `renting_homes_wales_act_2016` topic tag where relevant) so the retrieval layer can filter by jurisdiction when that distinction matters.

---

## Running the tests

```powershell
cd <repo root>
pytest knowledge/tests/ -v
```

Tests mock Ollama and spaCy — they do not require either to be installed.

---

## What never gets committed

```
data/raw/          # source documents
data/processed/    # extracted and scrubbed text
data/review/       # scrub reports and inventory CSV
```

All three are git-ignored (`.gitkeep` files preserve the directory structure). If in doubt, run `git status` before committing anything.
