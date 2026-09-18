import threading
import time
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
_GOOGLE_MODELS = frozenset({"gemini-embedding-2-preview"})

# One in-flight /api/embed at a time: parallel bge-m3 batches make Ollama's
# tokenizer subprocess drop connections (HTTP 400 "tokenize ... EOF").
_OLLAMA_EMBED_LOCK = threading.Lock()
_OLLAMA_BATCH_SIZE = 64
_OLLAMA_RETRIES = 3

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

    Defaults to bge-m3 on the local Ollama server (see LLM_EMBEDDING_MODEL).
    Swap `model` to another Ollama encoder (qwen3-embedding:0.6b,
    nomic-embed-text, jina-embeddings-v3) or to
    gemini-embedding-2-preview to use Google's API instead.
    """

    def __init__(
        self, base_url: str | None = None, model: EmbeddingModel | str | None = None
    ) -> None:
        self.base_url = base_url or settings.LLM_LOCAL_BASE_URL
        self.model = model or settings.LLM_EMBEDDING_MODEL

    def _canonical_model(self) -> str:
        return self.model.removesuffix(":latest")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._canonical_model()
        if model in _OLLAMA_MODELS:
            return self._embed_ollama(texts)
        if model in _GOOGLE_MODELS:
            return self._embed_google(texts)
        raise ValueError(
            f"Unknown embedding model {self.model!r}. "
            f"Use one of: {sorted(_OLLAMA_MODELS | _GOOGLE_MODELS)}"
        )

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        with _OLLAMA_EMBED_LOCK:
            for start in range(0, len(texts), _OLLAMA_BATCH_SIZE):
                batch = texts[start : start + _OLLAMA_BATCH_SIZE]
                embeddings.extend(self._embed_ollama_batch(batch))
        return embeddings

    def _embed_ollama_batch(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(_OLLAMA_RETRIES):
            try:
                response = httpx.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self._canonical_model(), "input": texts},
                    timeout=120.0,
                )
                if response.is_error:
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} {response.reason_phrase}: "
                        f"{response.text[:500]}",
                        request=response.request,
                        response=response,
                    )
                data = response.json()
                embeddings: list[list[float]] = data["embeddings"]
                return embeddings
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _embed_google(self, texts: list[str]) -> list[list[float]]:
        embedder = GoogleGenerativeAIEmbeddings(
            model=self._canonical_model(), task_type="RETRIEVAL_DOCUMENT"
        )
        return embedder.embed_documents(texts)
