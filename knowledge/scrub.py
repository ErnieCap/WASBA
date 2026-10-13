"""
knowledge/scrub.py
Personal-data scrubber for extracted document text.

Usage (PowerShell):
    python knowledge/scrub.py --source data/processed --out data/processed/scrubbed
                               --reports data/review/scrub_reports

Pipeline (three passes, all optional except the first):
  1. Regex — fast pattern matching for postcodes, phone numbers, NHS numbers,
             National Insurance numbers, email addresses, dates, URLs
  2. spaCy NER — named-entity recognition for PERSON, GPE (place), ORG
                 (disabled if spaCy model not installed)
  3. Ollama LLM — slower LLM review pass for anything the above may miss
                  (opt-in only; requires SCRUB_OLLAMA_ENABLED = True in config.py)

Output:
  - Scrubbed .txt files (placeholders like [PERSON_1], [POSTCODE_1])
  - JSON scrub report per file listing every redaction for human review
  - The "reviewed_by_owner" flag on ChunkMetadata must be set manually after review

IMPORTANT: Never send document text to any external or remote service.
All processing is local.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import (
    DATA_PROCESSED,
    DATA_REVIEW,
    OLLAMA_BASE_URL,
    OLLAMA_CHAT_MODEL,
    SCRUB_OLLAMA_ENABLED,
    SPACY_MODEL,
)
from schema import RedactionItem, ScrubReport

# ── Regex patterns ────────────────────────────────────────────────────────────

_PATTERNS: List[Tuple[str, str]] = [
    # UK postcode  (e.g. SW1A 2AA, LL11 2NX)
    (r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", "POSTCODE"),
    # UK phone — 11-digit starting 07 or 01/02; also 0800 etc.
    (r"\b0(?:7\d{3}|\d{3,4})\s?\d{3,4}\s?\d{3,4}\b", "PHONE"),
    # NHS number — 10 digits, optionally space/hyphen separated
    (r"\b\d{3}[\s\-]\d{3}[\s\-]\d{4}\b", "NHS_NUMBER"),
    # National Insurance number
    (r"\b[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", "NI_NUMBER"),
    # Email address
    (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "EMAIL"),
    # Full date patterns  (e.g. 12/03/2023, 12-03-2023, 12 March 2023)
    (
        r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b"
        r"|\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{2,4}\b",
        "DATE",
    ),
    # URLs
    (r"https?://[^\s]+", "URL"),
    # Street address fragments  (e.g. "12 Acacia Road", "Flat 3B, High Street")
    (
        r"\b(?:Flat|Apartment|Unit|No\.?|Number)\s+\d+[A-Za-z]?[\s,]+[A-Za-z]",
        "ADDRESS",
    ),
    (r"\b\d+[A-Za-z]?\s+[A-Z][a-z]+\s+(?:Road|Street|Avenue|Lane|Drive|Close|"
     r"Court|Place|Way|Terrace|Gardens?|Crescent|Row|Walk|View|Hill|Park)\b",
     "ADDRESS"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in _PATTERNS]


def _regex_redact(text: str) -> Tuple[str, List[RedactionItem]]:
    redactions: List[RedactionItem] = []
    counters: Dict[str, int] = {}
    replacements: List[Tuple[int, int, str]] = []

    for pattern, label in _COMPILED:
        for m in pattern.finditer(text):
            counters[label] = counters.get(label, 0) + 1
            placeholder = f"[{label}_{counters[label]}]"
            start, end = m.start(), m.end()
            ctx_start = max(0, start - 40)
            ctx_end = min(len(text), end + 40)
            redactions.append(
                RedactionItem(
                    label=label,
                    placeholder=placeholder,
                    original=m.group(),
                    context=text[ctx_start:ctx_end],
                    char_start=start,
                    char_end=end,
                    method="regex",
                )
            )
            replacements.append((start, end, placeholder))

    # Apply replacements in reverse order so offsets stay valid
    replacements.sort(key=lambda x: x[0], reverse=True)
    chars = list(text)
    for start, end, ph in replacements:
        chars[start:end] = list(ph)
    return "".join(chars), redactions


# ── spaCy NER pass ────────────────────────────────────────────────────────────

_NER_LABELS = {"PERSON", "GPE", "ORG", "LOC"}


def _spacy_redact(text: str) -> Tuple[str, List[RedactionItem], Optional[str]]:
    try:
        import spacy  # type: ignore
        try:
            nlp = spacy.load(SPACY_MODEL)
        except OSError:
            return text, [], f"spaCy model '{SPACY_MODEL}' not found — run: python -m spacy download {SPACY_MODEL}"

        doc = nlp(text)
        redactions: List[RedactionItem] = []
        counters: Dict[str, int] = {}
        replacements: List[Tuple[int, int, str]] = []

        for ent in doc.ents:
            if ent.label_ not in _NER_LABELS:
                continue
            label = ent.label_
            counters[label] = counters.get(label, 0) + 1
            placeholder = f"[{label}_{counters[label]}]"
            start, end = ent.start_char, ent.end_char
            ctx_start = max(0, start - 40)
            ctx_end = min(len(text), end + 40)
            redactions.append(
                RedactionItem(
                    label=label,
                    placeholder=placeholder,
                    original=ent.text,
                    context=text[ctx_start:ctx_end],
                    char_start=start,
                    char_end=end,
                    method="spacy_ner",
                )
            )
            replacements.append((start, end, placeholder))

        replacements.sort(key=lambda x: x[0], reverse=True)
        chars = list(text)
        for start, end, ph in replacements:
            chars[start:end] = list(ph)
        return "".join(chars), redactions, None

    except ImportError:
        return text, [], "spaCy not installed — run: pip install spacy"


# ── Ollama LLM pass ───────────────────────────────────────────────────────────

_OLLAMA_PROMPT = """You are a personal-data scrubber for a UK housing organisation.
The following text has already had obvious personal data replaced with placeholders.
Identify any REMAINING personal data: people's names, addresses, phone numbers,
dates of birth, NHS numbers, National Insurance numbers, or any other information
that could identify a real person.

Respond ONLY with a JSON array. Each item must have:
  "label": a short uppercase tag (e.g. "PERSON", "ADDRESS", "DOB")
  "original": the exact text that should be redacted
  "context": 60 characters of surrounding text

Example: [{"label": "PERSON", "original": "Mr Jones", "context": "...reported by Mr Jones last week..."}]

If nothing remains, respond with an empty array: []

TEXT TO CHECK:
"""


def _ollama_redact(text: str) -> Tuple[str, List[RedactionItem], Optional[str]]:
    import urllib.request  # stdlib only — no requests dependency

    payload = json.dumps({
        "model": OLLAMA_CHAT_MODEL,
        "messages": [{"role": "user", "content": _OLLAMA_PROMPT + text[:4000]}],
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
        raw_json = body.get("message", {}).get("content", "[]")
        # Extract JSON array from response (model may add preamble)
        match = re.search(r"\[.*?\]", raw_json, re.DOTALL)
        if not match:
            return text, [], None
        findings = json.loads(match.group())
    except Exception as exc:
        return text, [], f"Ollama LLM pass failed: {exc}"

    redactions: List[RedactionItem] = []
    counters: Dict[str, int] = {}
    result_text = text

    for item in findings:
        original = item.get("original", "")
        label = item.get("label", "UNKNOWN").upper()
        if not original or original not in result_text:
            continue
        counters[label] = counters.get(label, 0) + 1
        placeholder = f"[{label}_{counters[label]}]"
        idx = result_text.find(original)
        ctx_start = max(0, idx - 40)
        ctx_end = min(len(result_text), idx + len(original) + 40)
        redactions.append(
            RedactionItem(
                label=label,
                placeholder=placeholder,
                original=original,
                context=result_text[ctx_start:ctx_end],
                char_start=idx,
                char_end=idx + len(original),
                method="ollama",
            )
        )
        result_text = result_text.replace(original, placeholder, 1)

    return result_text, redactions, None


# ── Main scrubbing pipeline ───────────────────────────────────────────────────

def scrub_text(
    text: str,
    run_spacy: bool = True,
    run_ollama: bool = False,
) -> ScrubReport:
    """
    Run all enabled scrubbing passes on text.
    Returns a ScrubReport; the caller must supply source_file.
    """
    report = ScrubReport(source_file="")

    # Pass 1 — regex
    text, regex_redactions = _regex_redact(text)
    report.redactions.extend(regex_redactions)

    # Pass 2 — spaCy NER
    if run_spacy:
        text, spacy_redactions, spacy_error = _spacy_redact(text)
        report.redactions.extend(spacy_redactions)
        if spacy_error:
            print(f"  [scrub] spaCy: {spacy_error}")

    # Pass 3 — Ollama LLM
    if run_ollama:
        text, ollama_redactions, ollama_error = _ollama_redact(text)
        report.ollama_redactions.extend(ollama_redactions)
        if ollama_error:
            print(f"  [scrub] Ollama: {ollama_error}")

    return report, text


def scrub_file(
    source_path: Path,
    out_dir: Path,
    report_dir: Path,
    force: bool = False,
) -> bool:
    out_path = out_dir / source_path.name
    report_path = report_dir / (source_path.stem + "_scrub_report.json")

    if out_path.exists() and not force:
        print(f"  SKIP  {source_path.name}  (already scrubbed)")
        return True

    try:
        raw_text = source_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"  ERROR {source_path.name}: {exc}")
        return False

    print(f"  SCRUB {source_path.name}…")
    report, scrubbed_text = scrub_text(
        raw_text,
        run_spacy=True,
        run_ollama=SCRUB_OLLAMA_ENABLED,
    )
    report.source_file = source_path.name

    total = len(report.redactions) + len(report.ollama_redactions)
    print(f"        → {total} redaction(s) found")

    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    out_path.write_text(scrubbed_text, encoding="utf-8")
    report_path.write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"        → scrubbed text: {out_path}")
    print(f"        → report:        {report_path}")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrub personal data from extracted text files."
    )
    parser.add_argument(
        "--source", type=Path, default=DATA_PROCESSED,
        help="Folder of .txt files to scrub (default: data/processed)",
    )
    parser.add_argument(
        "--out", type=Path, default=DATA_PROCESSED / "scrubbed",
        help="Output folder for scrubbed files (default: data/processed/scrubbed)",
    )
    parser.add_argument(
        "--reports", type=Path, default=DATA_REVIEW / "scrub_reports",
        help="Folder for JSON scrub reports (default: data/review/scrub_reports)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-scrub files that already have output",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Source folder does not exist: {args.source}")
        sys.exit(1)

    txt_files = sorted(args.source.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files found in {args.source}")
        return

    print(f"Scrubbing {len(txt_files)} files…")
    ok = errors = 0
    for path in txt_files:
        if scrub_file(path, args.out, args.reports, force=args.force):
            ok += 1
        else:
            errors += 1

    print(f"\nDone: {ok} scrubbed, {errors} failed.")
    print("\nIMPORTANT: Review the scrub reports in", args.reports)
    print("Then set reviewed_by_owner = True in chunk metadata before embedding.")


if __name__ == "__main__":
    main()
