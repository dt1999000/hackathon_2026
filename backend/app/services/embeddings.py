from typing import Literal

import httpx
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import settings

# Embedding models pulled on the shared Ollama server and known to work with
# EmbeddingClient. bge-m3 and jina-embeddings-v3 are both strong multilingual
# encoders (100+ languages, including English/German) — prefer them over the
# defaults below for bid documents or queries that aren't English-only.
_OLLAMA_MODELS = frozenset(
    {"qwen3-embedding:0.6b", "nomic-embed-text", "bge-m3", "jina-embeddings-v3"}
)

# gemini-embedding-2-preview needs only GOOGLE_API_KEY (no local Ollama
# server) and is itself a strong multilingual encoder — a drop-in
# alternative to bge-m3/jina-embeddings-v3 for anyone without Ollama running.
EmbeddingModel = Literal[
    "qwen3-embedding:0.6b",
    "nomic-embed-text",
    "bge-m3",
    "jina-embeddings-v3",
    "gemini-embedding-2-preview",
]


class EmbeddingClient:
    """Client for computing text embeddings, from either the shared Ollama
    server or Google's Gemini embedding API depending on `model`.

    Defaults to a decoder-based model (qwen3-embedding) rather than a
    BERT-family encoder; swap `model` to compare against a BERT-family
    model like nomic-embed-text, to a multilingual model (bge-m3,
    jina-embeddings-v3) for non-English content, or to
    gemini-embedding-2-preview to use Google's API instead of Ollama.
    """

    def __init__(
        self, base_url: str | None = None, model: EmbeddingModel | None = None
    ) -> None:
        self.base_url = base_url or settings.LLM_LOCAL_BASE_URL
        self.model = model or settings.LLM_EMBEDDING_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.model in _OLLAMA_MODELS:
            return self._embed_ollama(texts)
        return self._embed_google(texts)

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        embeddings: list[list[float]] = data["embeddings"]
        return embeddings

    def _embed_google(self, texts: list[str]) -> list[list[float]]:
        embedder = GoogleGenerativeAIEmbeddings(
            model=self.model, task_type="RETRIEVAL_DOCUMENT"
        )
        return embedder.embed_documents(texts)
