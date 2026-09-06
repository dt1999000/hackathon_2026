from app.tools.rag.chunking.base import BaseChunker


class DefaultChunker(BaseChunker):
    """General-purpose chunker for plain/unstructured text with no
    format-specific separators. Use when no other chunker matches the
    source's format.
    """

    def __init__(self, chunk_size: int = 2000, chunk_overlap: int = 20, separators: list[str] | None = None, keep_separator: bool = True):
        super().__init__(chunk_size, chunk_overlap, separators, keep_separator)
