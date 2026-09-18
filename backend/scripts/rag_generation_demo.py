#!/usr/bin/env python
"""Compare local-model generation with vs. without RAG-retrieved context.

Usage:
    uv run python scripts/rag_generation_demo.py <source> <query> \
        [--loader json|tabular|github|youtube_video|youtube_channel|pdf] \
        [--chunker default|text|docx|mdx|web|csv|json|xml] \
        [--retrieval lexical|embedding] \
        [--embedding-model qwen3-embedding:0.6b|nomic-embed-text|bge-m3|jina-embeddings-v3] \
        [--top-k N]

Example:
    uv run python scripts/rag_generation_demo.py \
        https://github.com/firecrawl/firecrawl "What does this repo do?" \
        --loader github

    # Compare a BERT-family embedding model against the qwen3 default:
    uv run python scripts/rag_generation_demo.py \
        scripts/mock_data/company.json "Who is the CEO?" \
        --loader json --chunker json --embedding-model nomic-embed-text

    # Use a multilingual embedding model for non-English content:
    uv run python scripts/rag_generation_demo.py \
        scripts/mock_data/company.json "Wer ist der CEO?" \
        --loader json --chunker json --embedding-model bge-m3
"""

import argparse
from typing import get_args

from app.services.embeddings import EmbeddingClient, EmbeddingModel
from app.services.llm import LocalLLMClient
from app.tools.rag.chunking.base import BaseChunker
from app.tools.rag.chunking.default import DefaultChunker
from app.tools.rag.chunking.structured import CsvChunker, JsonChunker, XmlChunker
from app.tools.rag.chunking.text import DocxChunker, MdxChunker, TextChunker
from app.tools.rag.chunking.web import WebsiteChunker
from app.tools.rag.loader.base import BaseLoader, SourceContent
from app.tools.rag.loader.github import GithubLoader
from app.tools.rag.loader.json import JSONLoader
from app.tools.rag.loader.pdf import PDFLoader
from app.tools.rag.loader.tabular import TabularLoader
from app.tools.rag.loader.youtube_channel import YoutubeChannelLoader
from app.tools.rag.loader.youtube_video import YoutubeVideoLoader
from app.tools.rag.retrieval import retrieve_top_chunks, retrieve_top_chunks_embedding

LOADERS: dict[str, type[BaseLoader]] = {
    "json": JSONLoader,
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


def build_prompt(query: str, context_chunks: list[str]) -> str:
    context_block = "\n\n".join(context_chunks)
    return f"Use the following context to answer the question.\n\nContext:\n{context_block}\n\nQuestion: {query}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="Path or URL to load (matches the chosen --loader)")
    parser.add_argument("query", help="Question to ask the model")
    parser.add_argument("--loader", choices=sorted(LOADERS), default="github")
    parser.add_argument("--chunker", choices=sorted(CHUNKERS), default="default")
    parser.add_argument("--retrieval", choices=["embedding", "lexical"], default="embedding")
    parser.add_argument(
        "--embedding-model",
        choices=get_args(EmbeddingModel),
        default=None,
        help="Defaults to LLM_EMBEDDING_MODEL. bge-m3/jina-embeddings-v3 are multilingual.",
    )
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    loader = LOADERS[args.loader]()
    chunker = CHUNKERS[args.chunker]()
    client = LocalLLMClient()

    print(f"Loading '{args.source}' with {args.loader} loader...")
    result = loader.load(SourceContent(source=args.source))
    chunks = chunker.chunk(result.content)
    print(f"Loaded {len(result.content)} chars, split into {len(chunks)} chunks.\n")

    if args.retrieval == "lexical":
        context_chunks = retrieve_top_chunks(args.query, chunks, top_k=args.top_k)
    else:
        embedding_client = EmbeddingClient(model=args.embedding_model)
        print(f"Embedding with model: {embedding_client.model}")
        context_chunks = retrieve_top_chunks_embedding(
            args.query, chunks, top_k=args.top_k, embedding_client=embedding_client
        )
    print(f"Top {len(context_chunks)} retrieved chunk(s):")
    for i, chunk in enumerate(context_chunks, 1):
        preview = chunk[:150].replace("\n", " ")
        print(f"  {i}. {preview}...")
    print()

    print("=" * 80)
    print("WITHOUT RETRIEVAL (baseline)")
    print("=" * 80)
    baseline_answer = client.complete([{"role": "user", "content": args.query}])
    print(baseline_answer)

    print()
    print("=" * 80)
    print("WITH RETRIEVAL (context-augmented)")
    print("=" * 80)
    augmented_prompt = build_prompt(args.query, context_chunks)
    augmented_answer = client.complete([{"role": "user", "content": augmented_prompt}])
    print(augmented_answer)


if __name__ == "__main__":
    main()
