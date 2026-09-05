from typing import Any, cast

from fastapi import APIRouter
from pydantic import BaseModel

from app.tools.firecrawl_extract import FirecrawlExtractTool
from app.tools.firecrawl_scrape import FirecrawlScrapeWebsiteTool
from app.tools.firecrawl_search import FirecrawlSearchTool
from app.tools.firecrawl_website import FirecrawlCrawlWebsiteTool

router = APIRouter(tags=["tools"], prefix="/tools")


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
