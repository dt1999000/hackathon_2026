from typing import Any, cast

from fastapi import APIRouter
from pydantic import BaseModel

from app.tools.firecrawl_website import FirecrawlCrawlWebsiteTool

router = APIRouter(tags=["tools"], prefix="/tools")


class CrawlWebsiteRequest(BaseModel):
    url: str


@router.post("/firecrawl/crawl")
def crawl_website(request: CrawlWebsiteRequest) -> dict[str, Any]:
    """
    Dev-only endpoint to try out the Firecrawl crawl tool directly.
    """
    tool = FirecrawlCrawlWebsiteTool()
    return cast(dict[str, Any], tool.invoke({"url": request.url}))
