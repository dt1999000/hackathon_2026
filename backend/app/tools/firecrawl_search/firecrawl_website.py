from typing import Any, cast

from firecrawl import V1FirecrawlApp
from firecrawl.v1.client import V1ScrapeOptions
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class FirecrawlCrawlWebsiteToolSchema(BaseModel):
    url: str = Field(description="Website URL")


class FirecrawlCrawlWebsiteTool(BaseTool):
    """Tool for crawling websites using Firecrawl.

    Requires the FIRECRAWL_API_KEY environment variable (or an explicit
    api_key) to be set.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "firecrawl_crawl_website"
    description: str = "Crawl webpages using Firecrawl and return the contents"
    args_schema: type[BaseModel] = FirecrawlCrawlWebsiteToolSchema
    api_key: str | None = None
    config: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_depth": 2,
            "ignore_sitemap": True,
            "limit": 10,
            "allow_backward_links": False,
            "allow_external_links": False,
            "scrape_options": {
                "formats": ["markdown", "screenshot", "links"],
                "onlyMainContent": True,
                "timeout": 10000,
            },
        }
    )
    _firecrawl: V1FirecrawlApp = PrivateAttr()

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        self._firecrawl = V1FirecrawlApp(api_key=self.api_key)

    def _run(self, url: str) -> dict[str, Any]:
        scrape_options = V1ScrapeOptions(**self.config["scrape_options"])
        response = self._firecrawl.crawl_url(
            url,
            max_depth=self.config["max_depth"],
            ignore_sitemap=self.config["ignore_sitemap"],
            limit=self.config["limit"],
            allow_backward_links=self.config["allow_backward_links"],
            allow_external_links=self.config["allow_external_links"],
            scrape_options=scrape_options,
        )
        return cast(dict[str, Any], response.model_dump())
