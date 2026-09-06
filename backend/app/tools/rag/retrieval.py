import math
import re

from app.services.embeddings import EmbeddingClient


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def retrieve_top_chunks(query: str, chunks: list[str], top_k: int = 3) -> list[str]:
    """Rank chunks by lexical overlap with the query.

    Approximates relevance via Jaccard similarity between the query's and
    each chunk's word sets — no model call required. Useful as a cheap
    baseline to compare against embedding-based retrieval.
    """
    query_terms = _tokenize(query)
    if not query_terms:
        return chunks[:top_k]

    scored = []
    for chunk in chunks:
        chunk_terms = _tokenize(chunk)
        if not chunk_terms:
            continue
        overlap = len(query_terms & chunk_terms)
        if overlap == 0:
            continue
        union = len(query_terms | chunk_terms)
        score = overlap / union
        scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_top_chunks_embedding(
    query: str,
    chunks: list[str],
    top_k: int = 3,
    embedding_client: EmbeddingClient | None = None,
) -> list[str]:
    """Rank chunks by embedding cosine similarity to the query.

    Calls the shared Ollama server's embedding model (see
    app.services.embeddings.EmbeddingClient) for both the query and every
    chunk, then ranks by cosine similarity. More accurate than lexical
    overlap for paraphrased/semantic matches, at the cost of a model call
    per chunk.
    """
    if not chunks:
        return []

    client = embedding_client or EmbeddingClient()
    query_embedding = client.embed([query])[0]
    chunk_embeddings = client.embed(chunks)

    scored = [
        (_cosine_similarity(query_embedding, chunk_embedding), chunk)
        for chunk, chunk_embedding in zip(chunks, chunk_embeddings, strict=True)
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]
