from app.tools.rag.chunking.base import BaseChunker


class DefaultChunker(BaseChunker):
    """General-purpose chunker for plain/unstructured text with no
    format-specific separators. Use when no other chunker matches the
    source's format.

    Sized small (rather than the old 2000/20) so a short, unstructured
    document — e.g. a bid notice — splits into many fine-grained,
    roughly sentence-sized chunks instead of one or two large ones. A
    large chunk_size collapses distinct requirements (location,
    insurance, references, deadlines, ...) into the same chunk, so
    every profile section's best match converges on whichever single
    chunk happens to be keyword-dense, making retrieve_bid_context's
    similarity_score saturate at 1.0 regardless of actual per-section
    relevance. Sentence-ending punctuation is added to the separator
    hierarchy (absent from the plain \n/space fallback) so a 100-char
    cap still prefers breaking on a clean sentence/clause boundary
    over an arbitrary word boundary. chunk_overlap is kept to ~20% of
    chunk_size: enough to carry a boundary-split phrase into the next
    chunk, not so much that adjacent chunks become near-duplicates.
    """

    def __init__(self, chunk_size: int = 75, chunk_overlap: int = 10, separators: list[str] | None = None, keep_separator: bool = True):
        if separators is None:
            separators = [
                "\n\n",  # Paragraph breaks
                "\n",    # Line breaks
                ". ",    # Sentence endings
                "! ",    # Exclamation endings
                "? ",    # Question endings
                "; ",    # Semicolon breaks
                ", ",    # Comma breaks
                " ",     # Word breaks
                "",      # Character level
            ]
        super().__init__(chunk_size, chunk_overlap, separators, keep_separator)
