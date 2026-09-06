from typing import Any, cast

from firecrawl import V1FirecrawlApp
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class FirecrawlSearchToolSchema(BaseModel):
    query: str = Field(description="Search query")


class FirecrawlSearchTool(BaseTool):
    """Tool for searching the web using Firecrawl.

    Requires the FIRECRAWL_API_KEY environment variable (or an explicit
    api_key) to be set.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "firecrawl_search"
    description: str = "Search the web using Firecrawl and return the results"
    args_schema: type[BaseModel] = FirecrawlSearchToolSchema
    api_key: str | None = None
    config: dict[str, Any] = Field(
        default_factory=lambda: {
            "limit": 5,
            "tbs": None,
            "lang": "en",
            "country": "us",
            "location": None,
            "timeout": 60000,
        }
    )
    _firecrawl: V1FirecrawlApp = PrivateAttr()

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        self._firecrawl = V1FirecrawlApp(api_key=self.api_key)

    def _run(self, query: str) -> dict[str, Any]:
        response = self._firecrawl.search(query=query, **self.config)
        return cast(dict[str, Any], response.model_dump())
