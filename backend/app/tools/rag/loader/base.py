import hashlib
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class SourceContent:
    source: str

    @property
    def source_ref(self) -> str:
        return self.source

    def is_url(self) -> bool:
        return urlparse(self.source).scheme in ("http", "https")

    def path_exists(self) -> bool:
        return os.path.isfile(self.source)


@dataclass
class LoaderResult:
    content: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    doc_id: str = ""


class BaseLoader:
    def load(self, source_content: SourceContent, **kwargs: Any) -> LoaderResult:
        raise NotImplementedError

    def generate_doc_id(self, source_ref: str, content: str) -> str:
        return hashlib.sha256(f"{source_ref}:{content}".encode()).hexdigest()
