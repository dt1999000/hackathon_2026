from typing import Any, cast

from firecrawl.v2 import FirecrawlClient
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class FirecrawlExtractToolSchema(BaseModel):
    url: str = Field(description="Website URL to extract structured data from")
    json_schema: dict[str, Any] = Field(
        description=(
            "JSON Schema (type: object) describing the fields to extract. "
            "Every property must be listed in 'required' — the underlying "
            "model runs in strict structured-output mode."
        ),
    )
    prompt: str | None = Field(
        default=None,
        description="Optional natural-language guidance to accompany the schema",
    )


class FirecrawlExtractTool(BaseTool):
    """Extracts structured JSON matching a caller-supplied schema from a
    single webpage, instead of returning freeform markdown.

    Requires the FIRECRAWL_API_KEY environment variable (or an explicit
    api_key) to be set.

    Uses Firecrawl's v2 client (unlike the other Firecrawl tools here,
    which use v1): the dedicated v1 `/extract` endpoint is deprecated
    (maintenance mode, ~20x the credit cost) in favor of v2 `scrape` with
    a "json" format — see
    https://docs.firecrawl.dev/developer-guides/usage-guides/choosing-the-data-extractor.
    The format is passed as a plain dict rather than the SDK's JsonFormat
    model: JsonFormat serializes unset fields as explicit `null`, which
    the API's strict schema validation rejects (it expects the keys to be
    absent entirely).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "firecrawl_extract"
    description: str = "Extract structured data matching a JSON schema from a webpage using Firecrawl"
    args_schema: type[BaseModel] = FirecrawlExtractToolSchema
    api_key: str | None = None
    _firecrawl: FirecrawlClient = PrivateAttr()

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        self._firecrawl = FirecrawlClient(api_key=self.api_key)

    def _run(self, url: str, json_schema: dict[str, Any], prompt: str | None = None) -> dict[str, Any]:
        json_format: dict[str, Any] = {"type": "json", "schema": json_schema}
        if prompt is not None:
            json_format["prompt"] = prompt

        document = self._firecrawl.scrape(url, formats=[json_format])
        return cast(dict[str, Any], document.model_dump())
