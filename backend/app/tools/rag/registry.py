from app.tools.rag.chunking.base import BaseChunker
from app.tools.rag.chunking.default import DefaultChunker
from app.tools.rag.chunking.structured import CsvChunker, JsonChunker, XmlChunker
from app.tools.rag.chunking.text import DocxChunker, MdxChunker, TextChunker
from app.tools.rag.chunking.web import WebsiteChunker
from app.tools.rag.loader.base import BaseLoader
from app.tools.rag.loader.github import GithubLoader
from app.tools.rag.loader.json import JSONLoader
from app.tools.rag.loader.jsonl import JSONLLoader
from app.tools.rag.loader.pdf import PDFLoader
from app.tools.rag.loader.tabular import TabularLoader
from app.tools.rag.loader.youtube_channel import YoutubeChannelLoader
from app.tools.rag.loader.youtube_video import YoutubeVideoLoader

LOADERS: dict[str, type[BaseLoader]] = {
    "json": JSONLoader,
    "jsonl": JSONLLoader,
    "tabular": TabularLoader,
    "github": GithubLoader,
    "youtube_video": YoutubeVideoLoader,
    "youtube_channel": YoutubeChannelLoader,
    "pdf": PDFLoader,
}

CHUNKERS: dict[str, type[BaseChunker]] = {
    "default": DefaultChunker,
    "text": TextChunker,
    "docx": DocxChunker,
    "mdx": MdxChunker,
    "web": WebsiteChunker,
    "csv": CsvChunker,
    "json": JsonChunker,
    "xml": XmlChunker,
}


def get_loader(name: str) -> BaseLoader:
    loader_cls = LOADERS.get(name)
    if loader_cls is None:
        raise ValueError(f"Unknown loader '{name}'. Options: {list(LOADERS)}")
    return loader_cls()


def get_chunker(name: str) -> BaseChunker:
    chunker_cls = CHUNKERS.get(name)
    if chunker_cls is None:
        raise ValueError(f"Unknown chunker '{name}'. Options: {list(CHUNKERS)}")
    return chunker_cls()
