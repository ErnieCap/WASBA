"""Tests for knowledge/scrub.py — regex pass only (spaCy and Ollama are mocked)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrub import _regex_redact, scrub_file, scrub_text


# ── _regex_redact ─────────────────────────────────────────────────────────────

def test_redacts_uk_postcode():
    text = "The resident lives at LL11 2NX and reported noise."
    result, redactions = _regex_redact(text)
    assert "LL11 2NX" not in result
    assert "[POSTCODE_1]" in result
    labels = [r.label for r in redactions]
    assert "POSTCODE" in labels


def test_redacts_phone_number():
    text = "Please call 07700 900123 for more details."
    result, redactions = _regex_redact(text)
    assert "07700 900123" not in result
    assert "[PHONE_1]" in result


def test_redacts_email():
    text = "Contact resident.a@example.com directly."
    result, redactions = _regex_redact(text)
    assert "resident.a@example.com" not in result
    assert "[EMAIL_1]" in result


def test_redacts_ni_number():
    text = "NI number AB 12 34 56 C was used to verify identity."
    result, redactions = _regex_redact(text)
    assert "AB 12 34 56 C" not in result


def test_redacts_address():
    text = "Flat 3B, High Street was the subject property."
    result, redactions = _regex_redact(text)
    # Broad address pattern should catch the flat number
    assert any(r.label == "ADDRESS" for r in redactions)


def test_redacts_date():
    text = "The incident occurred on 12/03/2023 at 10pm."
    result, redactions = _regex_redact(text)
    assert "12/03/2023" not in result
    assert any(r.label == "DATE" for r in redactions)


def test_redacts_url():
    text = "See https://example.com/case/12345 for more."
    result, redactions = _regex_redact(text)
    assert "https://example.com/case/12345" not in result
    assert "[URL_1]" in result


def test_no_false_positive_on_clean_text():
    text = "The tenant reported a noise complaint from a neighbouring property."
    result, redactions = _regex_redact(text)
    assert result == text
    assert redactions == []


def test_multiple_redactions_numbered():
    text = (
        "Resident A (07700 900001) and Resident B (07700 900002) both complained."
    )
    result, redactions = _regex_redact(text)
    assert "[PHONE_1]" in result
    assert "[PHONE_2]" in result
    assert len([r for r in redactions if r.label == "PHONE"]) == 2


def test_redaction_item_fields():
    text = "Postcode: SW1A 2AA"
    _, redactions = _regex_redact(text)
    assert len(redactions) == 1
    item = redactions[0]
    assert item.original == "SW1A 2AA"
    assert item.method == "regex"
    assert "SW1A 2AA" in item.context
    assert item.char_start >= 0
    assert item.char_end > item.char_start


# ── scrub_text (with spaCy disabled) ─────────────────────────────────────────

def test_scrub_text_returns_report_and_text():
    text = "Contact 07700 900999 about the noise complaint."
    report, scrubbed = scrub_text(text, run_spacy=False, run_ollama=False)
    assert "07700 900999" not in scrubbed
    assert len(report.redactions) >= 1
    assert report.ollama_redactions == []


def test_scrub_text_clean_input():
    text = "The tenant reported noise from the adjoining property."
    report, scrubbed = scrub_text(text, run_spacy=False, run_ollama=False)
    assert scrubbed == text
    assert report.redactions == []


def test_scrub_text_spacy_unavailable(monkeypatch):
    """When spaCy is not installed, scrub_text should still succeed via regex."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "spacy":
            raise ImportError("mocked no spacy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    text = "SW1A 2AA is a fictional postcode."
    report, scrubbed = scrub_text(text, run_spacy=True, run_ollama=False)
    assert "SW1A 2AA" not in scrubbed  # regex still runs


# ── scrub_file ────────────────────────────────────────────────────────────────

def test_scrub_file_creates_output(tmp_path, monkeypatch):
    monkeypatch.setattr("scrub.SCRUB_OLLAMA_ENABLED", False)

    src = tmp_path / "source"
    src.mkdir()
    out = tmp_path / "scrubbed"
    reports = tmp_path / "reports"

    (src / "case_note.txt").write_text(
        "Fictional case note. Postcode LL11 2NX mentioned.",
        encoding="utf-8",
    )

    ok = scrub_file(src / "case_note.txt", out, reports)
    assert ok
    assert (out / "case_note.txt").exists()
    assert (reports / "case_note_scrub_report.json").exists()
    content = (out / "case_note.txt").read_text()
    assert "LL11 2NX" not in content
    assert "[POSTCODE_1]" in content


def test_scrub_file_skip_existing(tmp_path, monkeypatch):
    monkeypatch.setattr("scrub.SCRUB_OLLAMA_ENABLED", False)

    src = tmp_path / "source"
    src.mkdir()
    out = tmp_path / "scrubbed"
    out.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()

    (src / "note.txt").write_text("SW1A 2AA", encoding="utf-8")
    (out / "note.txt").write_text("previously scrubbed", encoding="utf-8")

    ok = scrub_file(src / "note.txt", out, reports)
    assert ok
    assert (out / "note.txt").read_text() == "previously scrubbed"


def test_scrub_file_force(tmp_path, monkeypatch):
    monkeypatch.setattr("scrub.SCRUB_OLLAMA_ENABLED", False)

    src = tmp_path / "source"
    src.mkdir()
    out = tmp_path / "scrubbed"
    out.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()

    (src / "note.txt").write_text("New fictional content SW1A 2AA", encoding="utf-8")
    (out / "note.txt").write_text("old", encoding="utf-8")

    ok = scrub_file(src / "note.txt", out, reports, force=True)
    assert ok
    assert "old" not in (out / "note.txt").read_text()
