"""Tests for knowledge/embed.py — Ollama is mocked throughout."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from embed import EmbeddingProvider, OllamaEmbedProvider, PaidEmbedProviderStub


# ── OllamaEmbedProvider properties ───────────────────────────────────────────

def test_model_name():
    provider = OllamaEmbedProvider(model="nomic-embed-text")
    assert provider.model_name == "nomic-embed-text"


def test_dimension_known_model():
    provider = OllamaEmbedProvider(model="nomic-embed-text")
    assert provider.dimension == 768


def test_dimension_unknown_model():
    provider = OllamaEmbedProvider(model="some-unknown-model")
    assert provider.dimension is None


# ── OllamaEmbedProvider.embed (mocked HTTP) ───────────────────────────────────

def _fake_urlopen(request, timeout=None):
    """Return a mock HTTP response with a 768-dim zero vector."""
    response_body = json.dumps({
        "embeddings": [[0.0] * 768, [0.1] * 768]
    }).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_embed_returns_vectors(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    provider = OllamaEmbedProvider()
    vectors = provider.embed(["fictional query one", "fictional query two"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 768


def test_embed_empty_list():
    provider = OllamaEmbedProvider()
    result = provider.embed([])
    assert result == []


def test_embed_raises_on_connection_error(monkeypatch):
    def failing_urlopen(request, timeout=None):
        raise ConnectionRefusedError("mocked connection refused")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    provider = OllamaEmbedProvider()
    with pytest.raises(RuntimeError) as exc_info:
        provider.embed(["test"])
    assert "Ollama" in str(exc_info.value)


def test_embed_raises_helpful_message_on_failure(monkeypatch):
    def failing_urlopen(request, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    provider = OllamaEmbedProvider()
    with pytest.raises(RuntimeError) as exc_info:
        provider.embed(["hello"])
    msg = str(exc_info.value)
    assert "ollama serve" in msg.lower() or "ollama" in msg.lower()


# ── PaidEmbedProviderStub ─────────────────────────────────────────────────────

def test_paid_stub_raises():
    stub = PaidEmbedProviderStub()
    with pytest.raises(NotImplementedError):
        stub.embed(["should raise"])


def test_paid_stub_model_name():
    stub = PaidEmbedProviderStub()
    assert stub.model_name == "stub"


def test_paid_stub_dimension_is_none():
    stub = PaidEmbedProviderStub()
    assert stub.dimension is None


# ── EmbeddingProvider ABC ─────────────────────────────────────────────────────

def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        EmbeddingProvider()


def test_ollama_is_embedding_provider():
    provider = OllamaEmbedProvider()
    assert isinstance(provider, EmbeddingProvider)


def test_stub_is_embedding_provider():
    stub = PaidEmbedProviderStub()
    assert isinstance(stub, EmbeddingProvider)


# ── Request format ────────────────────────────────────────────────────────────

def test_embed_sends_correct_model(monkeypatch):
    captured = {}

    def recording_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data)
        response_body = json.dumps({"embeddings": [[0.0] * 768]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    monkeypatch.setattr("urllib.request.urlopen", recording_urlopen)
    provider = OllamaEmbedProvider(model="nomic-embed-text")
    provider.embed(["test fictional text"])

    assert captured["body"]["model"] == "nomic-embed-text"
    assert captured["body"]["input"] == ["test fictional text"]
