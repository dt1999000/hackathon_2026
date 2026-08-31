import re


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def retrieve_top_chunks(query: str, chunks: list[str], top_k: int = 3) -> list[str]:
    """Rank chunks by lexical overlap with the query.

    No embedding model is wired up yet, so relevance is approximated by
    Jaccard similarity between the query's and each chunk's word sets. Good
    enough for dev comparisons; swap for embedding-based similarity once a
    vector store is in place.
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
