import re


class RecursiveCharacterTextSplitter:
    """
    A text splitter that recursively splits text based on a hierarchy of separators.
    """

    def __init__(
        self,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        separators: list[str] | None = None,
        keep_separator: bool = True,
    ):
        """
        Initialize the RecursiveCharacterTextSplitter.

        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Number of characters to overlap between chunks
            separators: List of separators to use for splitting (in order of preference)
            keep_separator: Whether to keep the separator in the split text
        """
        if chunk_overlap >= chunk_size:
            raise ValueError(f"Chunk overlap ({chunk_overlap}) cannot be >= chunk size ({chunk_size})")

        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._keep_separator = keep_separator

        self._separators = separators or [
            "\n\n",
            "\n",
            " ",
            "",
        ]

    def split_text(self, text: str) -> list[str]:
        # Recursive splitting only produces a flat list of atomic pieces
        # (each always < chunk_size); merging/overlap is then applied
        # exactly once, globally, over that flat list. Doing both in one
        # pass per recursion level — as this used to — meant a child
        # call's already-overlapping merged chunks got fed back into
        # the parent's own merge as if they were fresh, non-overlapping
        # splits: joining two children that already shared carried-over
        # overlap text duplicated that text inside the resulting chunk,
        # and joining pieces that already carry their own leading
        # separator (keep_separator) with `separator.join(...)` again
        # doubled the separator (e.g. "\n" -> "\n\n"). Splitting deep
        # (small chunk_size) made both far more visible since it forces
        # many recursion levels.
        atomic_pieces = self._split_recursive(text, self._separators)
        return self._merge_splits(atomic_pieces)

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        """Pure splitting, no merging: returns a flat list of atomic
        pieces whose concatenation reproduces `text` (when
        keep_separator, each piece already carries its own leading
        separator — see `_split_text_with_separator`). Every returned
        piece is guaranteed < chunk_size, since the character-level
        fallback (separator == "") always yields chunk_size-sized
        slices."""
        separator = separators[-1]
        new_separators: list[str] = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = sep
                break
            if re.search(re.escape(sep), text):
                separator = sep
                new_separators = separators[i + 1:]
                break

        splits = self._split_text_with_separator(text, separator)

        atomic_pieces = []

        for split in splits:
            if len(split) < self._chunk_size:
                atomic_pieces.append(split)
            elif new_separators:
                atomic_pieces.extend(self._split_recursive(split, new_separators))
            else:
                atomic_pieces.extend(self._split_by_characters(split))

        return atomic_pieces

    def _split_text_with_separator(self, text: str, separator: str) -> list[str]:
        if separator == "":
            return list(text)

        if self._keep_separator and separator in text:
            parts = text.split(separator)
            splits = []

            for i, part in enumerate(parts):
                if i == 0:
                    splits.append(part)
                elif i == len(parts) - 1:
                    if part:
                        splits.append(separator + part)
                else:
                    if part:
                        splits.append(separator + part)
                    else:
                        if splits:
                            splits[-1] += separator

            return [s for s in splits if s]
        else:
            return text.split(separator)

    def _split_by_characters(self, text: str) -> list[str]:
        chunks = []
        for i in range(0, len(text), self._chunk_size):
            chunks.append(text[i:i + self._chunk_size])
        return chunks

    def _merge_splits(self, splits: list[str]) -> list[str]:
        """Single global merge pass over the fully flattened list of
        atomic pieces from `_split_recursive`: greedily pack pieces into
        chunks up to chunk_size, carrying up to chunk_overlap trailing
        characters into the next chunk by dropping whole pieces off the
        front. Every piece here is atomic — never a previously merged,
        already-overlapping chunk — which is what makes a single pass
        safe: merging pre-merged, already-overlapping results (the old
        per-recursion-level approach) duplicated whatever text two
        adjacent results already shared as overlap. With keep_separator
        (the only mode any chunker in this codebase uses), each piece
        already carries its own leading separator, so chunks are formed
        by plain concatenation rather than joining with a separator
        again, which used to double it up (e.g. "\\n" -> "\\n\\n").
        """
        docs: list[str] = []
        current: list[str] = []
        total = 0

        def joined(parts: list[str]) -> str:
            return "".join(parts) if self._keep_separator else " ".join(parts)

        for split in splits:
            split_len = len(split)

            if total + split_len > self._chunk_size and current:
                doc = joined(current)
                if doc:
                    docs.append(doc)

                # Handle overlap by keeping some of the previous content
                while total > self._chunk_overlap and len(current) > 1:
                    removed = current.pop(0)
                    total -= len(removed)

            current.append(split)
            total += split_len

        if current:
            doc = joined(current)
            if doc:
                docs.append(doc)

        return docs

class BaseChunker:
    """Base class for RAG chunkers: splits a loaded document's text into
    overlapping chunks sized for embedding/retrieval, via
    RecursiveCharacterTextSplitter. Subclasses just supply
    format-appropriate defaults (chunk size and separator preference order)
    — call `.chunk(text)` to get the list of chunks.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200, separators: list[str] | None = None, keep_separator: bool = True):
        """
        Initialize the Chunker

        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Number of characters to overlap between chunks
            separators: List of separators to use for splitting
            keep_separator: Whether to keep separators in the chunks
        """

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            keep_separator=keep_separator,
        )


    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        return self._splitter.split_text(text)
