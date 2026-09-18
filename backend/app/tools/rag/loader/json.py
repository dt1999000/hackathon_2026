import json
from typing import Any

import requests

from app.tools.rag.loader.base import BaseLoader, LoaderResult, SourceContent


def flatten_json_to_text(data: Any) -> str:
    """Render parsed JSON as readable "key: value" (dict) or line-per-item
    (list) text, suitable for chunking. Shared by JSONLoader and
    JSONLLoader so both format records the same way."""
    if isinstance(data, dict):
        return "\n".join(f"{k}: {json.dumps(v, indent=0)}" for k, v in data.items())
    if isinstance(data, list):
        return "\n".join(json.dumps(item, indent=0) for item in data)
    return json.dumps(data, indent=0)


class JSONLoader(BaseLoader):
    """Loads a JSON document from a local file path or an http(s) URL.

    `source_content.source` is the path or URL. Flattens the JSON into a
    readable "key: value" (dict) or line-per-item (list) text form for
    chunking; falls back to the raw content on parse errors.
    """

    def load(self, source_content: SourceContent, **kwargs: Any) -> LoaderResult:
        source_ref = source_content.source_ref
        content = source_content.source

        if source_content.is_url():
            content = self._load_from_url(source_ref, kwargs)
        elif source_content.path_exists():
            content = self._load_from_file(source_ref)

        return self._parse_json(content, source_ref)

    def _load_from_url(self, url: str, kwargs: dict[str, Any]) -> str:
        headers = kwargs.get(
            "headers",
            {
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; app JSONLoader)",
            },
        )

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return (
                response.text
                if not self._is_json_response(response)
                else json.dumps(response.json(), indent=2)
            )
        except Exception as e:
            raise ValueError(f"Error fetching JSON from URL {url}: {e}") from e

    def _is_json_response(self, response: requests.Response) -> bool:
        try:
            response.json()
            return True
        except ValueError:
            return False

    def _load_from_file(self, path: str) -> str:
        with open(path, encoding="utf-8") as file:
            return file.read()

    def _parse_json(self, content: str, source_ref: str) -> LoaderResult:
        try:
            data = json.loads(content)
            text = flatten_json_to_text(data)

            metadata: dict[str, Any] = {
                "format": "json",
                "type": type(data).__name__,
                "size": len(data) if isinstance(data, list | dict) else 1,
            }
        except json.JSONDecodeError as e:
            text = content
            metadata = {"format": "json", "parse_error": str(e)}

        return LoaderResult(
            content=text,
            source=source_ref,
            metadata=metadata,
            doc_id=self.generate_doc_id(source_ref=source_ref, content=text),
        )
