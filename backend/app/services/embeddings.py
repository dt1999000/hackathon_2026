import httpx

from app.core.config import settings


class EmbeddingClient:
    """Client for the shared Ollama server's embedding endpoint.

    Defaults to a decoder-based model (qwen3-embedding) rather than a
    BERT-family encoder; swap `model` to compare against a BERT-family
    model like nomic-embed-text.
    """

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
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
