from typing import Any, cast

from firecrawl import V1FirecrawlApp
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class FirecrawlScrapeWebsiteToolSchema(BaseModel):
    url: str = Field(description="Website URL")


class FirecrawlScrapeWebsiteTool(BaseTool):
    """Tool for scraping a single webpage using Firecrawl.

    Requires the FIRECRAWL_API_KEY environment variable (or an explicit
    api_key) to be set.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "firecrawl_scrape_website"
    description: str = "Scrape a webpage using Firecrawl and return the contents"
    args_schema: type[BaseModel] = FirecrawlScrapeWebsiteToolSchema
    api_key: str | None = None
    config: dict[str, Any] = Field(
        default_factory=lambda: {
            "formats": ["markdown"],
            "only_main_content": True,
            "include_tags": [],
            "exclude_tags": [],
            "headers": {},
            "wait_for": 0,
        }
    )
    _firecrawl: V1FirecrawlApp = PrivateAttr()

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        self._firecrawl = V1FirecrawlApp(api_key=self.api_key)

    def _run(self, url: str) -> dict[str, Any]:
        response = self._firecrawl.scrape_url(url, **self.config)
        return cast(dict[str, Any], response.model_dump())
