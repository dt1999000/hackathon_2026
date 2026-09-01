from app.tools.rag.chunking.base import BaseChunker


class CsvChunker(BaseChunker):
    """Chunker for CSVLoader's "Row N: col: value | ..." text output,
    splitting on row boundaries so each chunk stays row-aligned.
    """

    def __init__(self, chunk_size: int = 1200, chunk_overlap: int = 100, separators: list[str] | None = None, keep_separator: bool = True):
        if separators is None:
            separators = [
                "\nRow ",   # Row boundaries (from CSVLoader format)
                "\n",       # Line breaks
                " | ",      # Column separators
                ", ",       # Comma separators
                " ",        # Word breaks
                "",         # Character level
            ]
        super().__init__(chunk_size, chunk_overlap, separators, keep_separator)


class JsonChunker(BaseChunker):
    """Chunker for JSONLoader's "key: value" text output, splitting on
    object/array boundaries before falling back to line/word splits.
    """

    def __init__(self, chunk_size: int = 2000, chunk_overlap: int = 200, separators: list[str] | None = None, keep_separator: bool = True):
        if separators is None:
            separators = [
                "\n\n",     # Object/array boundaries
                "\n",       # Line breaks
                "},",       # Object endings
                "],",       # Array endings
                ", ",       # Property separators
                ": ",       # Key-value separators
                " ",        # Word breaks
                "",         # Character level
            ]
        super().__init__(chunk_size, chunk_overlap, separators, keep_separator)


class XmlChunker(BaseChunker):
    """Chunker for XML/HTML-like text, splitting on element/tag boundaries
    before falling back to sentence/word splits.
    """

    def __init__(self, chunk_size: int = 2500, chunk_overlap: int = 250, separators: list[str] | None = None, keep_separator: bool = True):
        if separators is None:
            separators = [
                "\n\n",     # Element boundaries
                "\n",       # Line breaks
                ">",        # Tag endings
                ". ",       # Sentence endings (for text content)
                "! ",       # Exclamation endings
                "? ",       # Question endings
                ", ",       # Comma separators
                " ",        # Word breaks
                "",         # Character level
            ]
        super().__init__(chunk_size, chunk_overlap, separators, keep_separator)
