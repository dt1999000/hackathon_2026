import hashlib
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class SourceContent:
    """Wraps a raw source reference (URL or filesystem path) passed to a loader."""

    source: str

    @property
    def source_ref(self) -> str:
        """The original reference string, for use in metadata/doc IDs."""
        return self.source

    def is_url(self) -> bool:
        """True if `source` is an http(s) URL rather than a local path."""
        return urlparse(self.source).scheme in ("http", "https")

    def path_exists(self) -> bool:
        """True if `source` is a path to a file that exists on disk."""
        return os.path.isfile(self.source)


@dataclass
class LoaderResult:
    """What a loader returns: extracted text plus metadata for downstream chunking/retrieval."""

    content: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    doc_id: str = ""


class BaseLoader:
    """Base class for RAG source loaders.

    Subclasses fetch/read from a specific source type (file, URL, API) and
    return the extracted text as a `LoaderResult`, ready for chunking.
    """

    def load(self, source_content: SourceContent, **kwargs: Any) -> LoaderResult:
        raise NotImplementedError

    def generate_doc_id(self, source_ref: str, content: str) -> str:
        """Deterministic ID for a loaded document, derived from its source and content."""
        return hashlib.sha256(f"{source_ref}:{content}".encode()).hexdigest()
