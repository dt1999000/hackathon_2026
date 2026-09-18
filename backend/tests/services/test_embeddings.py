from unittest.mock import MagicMock, patch

import pytest

from app.services.embeddings import EmbeddingClient


def test_embed_uses_ollama_for_bge_m3() -> None:
    client = EmbeddingClient(base_url="http://ollama.test", model="bge-m3")
    mock_response = MagicMock()
    mock_response.is_error = False
    mock_response.json.return_value = {"embeddings": [[0.1, 0.2]]}

    with patch("app.services.embeddings.httpx.post", return_value=mock_response) as post:
        result = client.embed(["hello"])

    post.assert_called_once_with(
        "http://ollama.test/api/embed",
        json={"model": "bge-m3", "input": ["hello"]},
        timeout=120.0,
    )
    assert result == [[0.1, 0.2]]


def test_embed_accepts_ollama_latest_tag() -> None:
    client = EmbeddingClient(base_url="http://ollama.test", model="bge-m3:latest")
    mock_response = MagicMock()
    mock_response.is_error = False
    mock_response.json.return_value = {"embeddings": [[0.5]]}

    with patch("app.services.embeddings.httpx.post", return_value=mock_response) as post:
        result = client.embed(["hello"])

    post.assert_called_once_with(
        "http://ollama.test/api/embed",
        json={"model": "bge-m3", "input": ["hello"]},
        timeout=120.0,
    )
    assert result == [[0.5]]


def test_embed_keeps_google_for_gemini() -> None:
    client = EmbeddingClient(model="gemini-embedding-2-preview")

    with patch("app.services.embeddings.GoogleGenerativeAIEmbeddings") as google:
        google.return_value.embed_documents.return_value = [[0.3, 0.4]]
        result = client.embed(["hello"])

    google.assert_called_once_with(
        model="gemini-embedding-2-preview", task_type="RETRIEVAL_DOCUMENT"
    )
    google.return_value.embed_documents.assert_called_once_with(["hello"])
    assert result == [[0.3, 0.4]]


def test_embed_ollama_batches_large_inputs() -> None:
    client = EmbeddingClient(base_url="http://ollama.test", model="bge-m3")
    mock_response = MagicMock()
    mock_response.is_error = False
    mock_response.json.side_effect = [
        {"embeddings": [[0.1]] * 64},
        {"embeddings": [[0.2]] * 6},
    ]

    with patch("app.services.embeddings.httpx.post", return_value=mock_response) as post:
        result = client.embed([f"t{i}" for i in range(70)])

    assert post.call_count == 2
    assert len(result) == 70


def test_embed_rejects_unknown_model() -> None:
    client = EmbeddingClient(model="not-a-real-model")
    with pytest.raises(ValueError, match="Unknown embedding model"):
        client.embed(["hello"])
