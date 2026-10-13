"""
knowledge/config.py
Central configuration for the knowledge pipeline.
Edit values here — do not hard-code them in the scripts.
"""
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
DATA_RAW       = REPO_ROOT / "data" / "raw"        # source documents (git-ignored)
DATA_PROCESSED = REPO_ROOT / "data" / "processed"  # extracted text + chunks (git-ignored)
DATA_REVIEW    = REPO_ROOT / "data" / "review"     # redaction reports (git-ignored)

# ── Ollama ─────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL    = "http://localhost:11434"
OLLAMA_EMBED_MODEL = "nomic-embed-text"   # pull with: ollama pull nomic-embed-text
OLLAMA_CHAT_MODEL  = "llama3"             # used only if SCRUB_OLLAMA_ENABLED = True

# ── Chunking ───────────────────────────────────────────────────────────────
CHUNK_TARGET_CHARS = 1800   # ~450 tokens at 4 chars/token; tune to taste
CHUNK_OVERLAP_CHARS = 200   # overlap between adjacent chunks

# ── spaCy ──────────────────────────────────────────────────────────────────
SPACY_MODEL = "en_core_web_sm"   # install with: python -m spacy download en_core_web_sm

# ── Scrubber ───────────────────────────────────────────────────────────────
SCRUB_OLLAMA_ENABLED = False    # off by default; set True to run the Ollama LLM pass
SCRUB_SIMILARITY_THRESHOLD = 0.80   # Jaccard threshold for near-duplicate detection

# ── Evaluation ─────────────────────────────────────────────────────────────
EVAL_K_VALUES = [1, 3, 5, 10]   # k values for hit-rate-at-k scoring
