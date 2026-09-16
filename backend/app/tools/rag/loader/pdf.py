from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.tools.rag.loader.base import BaseLoader, LoaderResult, SourceContent


class PDFLoader(BaseLoader):
    """Loads text from a local PDF file.

    `source_content.source` must be a path to an existing PDF file. Renders
    each page as "Page N:\\n<text>", skipping pages with no extractable text
    (e.g. scanned images without OCR).
    """

    def load(self, source_content: SourceContent, **kwargs: Any) -> LoaderResult:
        source_ref = source_content.source_ref

        if not source_content.path_exists():
            raise FileNotFoundError(f"PDF file not found: {source_ref}")

        try:
            reader = PdfReader(source_ref)
        except Exception as e:
            raise ValueError(f"Error reading PDF file {source_ref}: {e}") from e

        pages = []
        for page_num, page in enumerate(reader.pages, 1):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                pages.append(f"Page {page_num}:\n{page_text}")

        content = (
            "\n\n".join(pages)
            if pages
            else f"[PDF file with no extractable text: {Path(source_ref).name}]"
        )

        metadata: dict[str, Any] = {
            "format": "pdf",
            "file_name": Path(source_ref).name,
            "num_pages": len(reader.pages),
        }

        return LoaderResult(
            content=content,
            source=source_ref,
            metadata=metadata,
            doc_id=self.generate_doc_id(source_ref=source_ref, content=content),
        )
