from typing import Literal

import httpx

from app.core.config import settings

# Embedding models pulled on the shared Ollama server and known to work with
# EmbeddingClient. bge-m3 and jina-embeddings-v3 are both strong multilingual
# encoders (100+ languages, including English/German) — prefer them over the
# defaults below for bid documents or queries that aren't English-only.
EmbeddingModel = Literal[
    "qwen3-embedding:0.6b",
    "nomic-embed-text",
    "bge-m3",
    "jina-embeddings-v3",
]


class EmbeddingClient:
    """Client for the shared Ollama server's embedding endpoint.

    Defaults to a decoder-based model (qwen3-embedding) rather than a
    BERT-family encoder; swap `model` to compare against a BERT-family
    model like nomic-embed-text, or to a multilingual model (bge-m3,
    jina-embeddings-v3) for non-English content.
    """

    def __init__(
        self, base_url: str | None = None, model: EmbeddingModel | None = None
    ) -> None:
        self.base_url = base_url or settings.LLM_LOCAL_BASE_URL
        self.model = model or settings.LLM_EMBEDDING_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        embeddings: list[list[float]] = data["embeddings"]
        return embeddings
