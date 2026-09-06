from app.tools.rag.chunking.base import BaseChunker


class WebsiteChunker(BaseChunker):
    """Chunker for scraped/crawled webpage content (e.g. Firecrawl markdown
    output), splitting on section/paragraph/sentence boundaries.
    """

    def __init__(self, chunk_size: int = 2500, chunk_overlap: int = 250, separators: list[str] | None = None, keep_separator: bool = True):
        if separators is None:
            separators = [
                "\n\n\n",  # Major section breaks
                "\n\n",    # Paragraph breaks
                "\n",      # Line breaks
                ". ",      # Sentence endings
                "! ",      # Exclamation endings
                "? ",      # Question endings
                "; ",      # Semicolon breaks
                ", ",      # Comma breaks
                " ",       # Word breaks
                "",        # Character level
            ]
        super().__init__(chunk_size, chunk_overlap, separators, keep_separator)
