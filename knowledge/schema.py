"""
knowledge/schema.py
Pydantic models for chunk metadata.

Every chunk stored in the vector database carries one ChunkMetadata record.
Edit DocumentType, Jurisdiction, and the tag vocabulary in tags.yaml —
the schema is intentionally kept separate from the tags list so adding a
new tag doesn't require a code change.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    GUIDANCE         = "guidance"           # practice guidance, good-practice notes
    CASE_REFLECTION  = "case_reflection"    # anonymised case learning
    LEGISLATION_NOTE = "legislation_note"   # notes on Acts, statutory guidance
    PROCEDURE        = "procedure"          # step-by-step operating procedures
    TEMPLATE         = "template"           # document templates
    OTHER            = "other"


class Jurisdiction(str, Enum):
    WALES    = "Wales"      # Wales-specific (e.g. Renting Homes (Wales) Act 2016)
    ENGLAND  = "England"    # England-specific
    UK_WIDE  = "UK-wide"    # applies to both
    UNKNOWN  = "unknown"


class ChunkMetadata(BaseModel):
    """Metadata attached to every chunk before and after embedding."""

    # Identity
    chunk_id: str = Field(..., description="Unique ID: <source_hash[:8]>-<chunk_index>")
    source_file: str = Field(..., description="Original filename (no path)")
    source_hash: str = Field(..., description="SHA-256 of the source file at extraction time")

    # Classification (owner fills these in or confirms auto-detected values)
    document_type: DocumentType = DocumentType.OTHER
    topic_tags: List[str] = Field(
        default_factory=list,
        description="One or more tags from tags.yaml",
    )
    jurisdiction: Jurisdiction = Jurisdiction.UNKNOWN
    document_date: Optional[str] = Field(
        None,
        description="ISO date, year, or range (e.g. '2024', '2022-2024') if known",
    )

    # Structure
    heading_path: List[str] = Field(
        default_factory=list,
        description="Breadcrumb of headings leading to this chunk, e.g. ['Section 1', 'Noise']",
    )
    chunk_index: int = Field(..., description="Zero-based position in the source document")
    text: str = Field(..., description="Chunk text after scrubbing")

    # Quality gate
    reviewed_by_owner: bool = Field(
        False,
        description="Set to True after the owner has manually checked the scrub report",
    )

    # Embedding provenance — recorded so different models can't be mixed silently
    embed_model: Optional[str] = Field(None, description="Ollama model name used for embedding")
    embed_dimension: Optional[int] = Field(None, description="Vector dimension produced by that model")

    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class ScrubReport(BaseModel):
    """Output of the personal-data scrubber for one file."""

    source_file: str
    scrub_date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    redactions: List[RedactionItem] = Field(default_factory=list)
    ollama_redactions: List[RedactionItem] = Field(default_factory=list)
    reviewed: bool = False


class RedactionItem(BaseModel):
    """One detected piece of personal data."""

    label: str              # e.g. "PERSON", "POSTCODE", "PHONE"
    placeholder: str        # e.g. "[PERSON_1]"
    original: str           # the text that was replaced
    context: str            # surrounding 80 chars for human review
    char_start: int
    char_end: int
    method: str             # "regex", "spacy_ner", or "ollama"


# Pydantic forward-reference update (Python 3.9 compat)
ScrubReport.model_rebuild()
