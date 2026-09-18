from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.embeddings import EmbeddingClient
from app.services.llm import LocalLLMClient
from app.tools.firecrawl_search.firecrawl_extract import FirecrawlExtractTool
from app.tools.firecrawl_search.firecrawl_scrape import FirecrawlScrapeWebsiteTool
from app.tools.firecrawl_search.firecrawl_search import FirecrawlSearchTool
from app.tools.firecrawl_search.firecrawl_website import FirecrawlCrawlWebsiteTool
from app.tools.rag.loader.base import SourceContent
from app.tools.rag.registry import BaseChunker, BaseLoader
from app.tools.rag.registry import get_chunker as _registry_get_chunker
from app.tools.rag.registry import get_loader as _registry_get_loader
from app.tools.rag.retrieval import retrieve_top_chunks, retrieve_top_chunks_embedding

router = APIRouter(tags=["tools"], prefix="/tools")


def _get_loader(name: str) -> BaseLoader:
    try:
        return _registry_get_loader(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _get_chunker(name: str) -> BaseChunker:
    try:
        return _registry_get_chunker(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class LoadRequest(BaseModel):
    source: str
    loader: str


class ChunkRequest(BaseModel):
    text: str
    chunker: str = "default"


class IngestRequest(BaseModel):
    source: str
    loader: str
    chunker: str = "default"


class CompleteRequest(BaseModel):
    messages: list[dict[str, str]]


class GenerateRequest(BaseModel):
    source: str
    loader: str
    query: str
    chunker: str = "default"
    top_k: int = 3
    use_retrieval: bool = True
    retrieval_method: str = "embedding"  # "embedding" or "lexical"
    embedding_model: str | None = None  # override to compare models, e.g. "nomic-embed-text"


class CrawlWebsiteRequest(BaseModel):
    url: str


class ScrapeWebsiteRequest(BaseModel):
    url: str


class SearchRequest(BaseModel):
    query: str


class ExtractRequest(BaseModel):
    url: str
    json_schema: dict[str, Any]
    prompt: str | None = None


@router.post("/rag/load")
def load_source(request: LoadRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to try out a RAG loader directly.
    """
    loader = _get_loader(request.loader)
    result = loader.load(SourceContent(source=request.source))
    return {
        "content": result.content,
        "source": result.source,
        "metadata": result.metadata,
        "doc_id": result.doc_id,
    }


@router.post("/rag/chunk")
def chunk_text(request: ChunkRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to try out a RAG chunker directly.
    """
    chunker = _get_chunker(request.chunker)
    return {"chunks": chunker.chunk(request.text)}


@router.post("/rag/ingest")
def ingest_source(request: IngestRequest) -> dict[str, Any]:
    """
    Dev-only endpoint: load a source and chunk its content in one call.
    """
    loader = _get_loader(request.loader)
    chunker = _get_chunker(request.chunker)
    result = loader.load(SourceContent(source=request.source))
    chunks = chunker.chunk(result.content)
    return {
        "source": result.source,
        "metadata": result.metadata,
        "doc_id": result.doc_id,
        "chunks": chunks,
    }


@router.post("/llm/complete")
def complete(request: CompleteRequest) -> dict[str, str]:
    """
    Dev-only endpoint to try out the local LLM client directly.
    """
    client = LocalLLMClient()
    return {"content": client.complete(request.messages)}


@router.post("/rag/generate")
def generate(request: GenerateRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to compare generation with vs. without retrieved
    context from a RAG source.
    """
    loader = _get_loader(request.loader)
    chunker = _get_chunker(request.chunker)
    client = LocalLLMClient()

    result = loader.load(SourceContent(source=request.source))
    chunks = chunker.chunk(result.content)

    context_used: list[str] = []
    if request.use_retrieval:
        if request.retrieval_method == "lexical":
            context_used = retrieve_top_chunks(request.query, chunks, top_k=request.top_k)
        else:
            embedding_client = EmbeddingClient(model=request.embedding_model)
            context_used = retrieve_top_chunks_embedding(
                request.query, chunks, top_k=request.top_k, embedding_client=embedding_client
            )
        context_block = "\n\n".join(context_used)
        prompt = (
            f"Use the following context to answer the question.\n\n"
            f"Context:\n{context_block}\n\nQuestion: {request.query}"
        )
    else:
        prompt = request.query

    answer = client.complete([{"role": "user", "content": prompt}])
    return {"answer": answer, "context_used": context_used}


@router.post("/firecrawl/crawl")
def crawl_website(request: CrawlWebsiteRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to try out the Firecrawl crawl tool directly.
    """
    tool = FirecrawlCrawlWebsiteTool()
    return cast(dict[str, Any], tool.invoke({"url": request.url}))


@router.post("/firecrawl/scrape")
def scrape_website(request: ScrapeWebsiteRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to try out the Firecrawl scrape tool directly.
    """
    tool = FirecrawlScrapeWebsiteTool()
    return cast(dict[str, Any], tool.invoke({"url": request.url}))


@router.post("/firecrawl/search")
def search(request: SearchRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to try out the Firecrawl search tool directly.
    """
    tool = FirecrawlSearchTool()
    return cast(dict[str, Any], tool.invoke({"query": request.query}))


@router.post("/firecrawl/extract")
def extract(request: ExtractRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to try out the Firecrawl structured-extraction tool directly.
    """
    tool = FirecrawlExtractTool()
    return cast(
        dict[str, Any],
        tool.invoke({"url": request.url, "json_schema": request.json_schema, "prompt": request.prompt}),
    )
