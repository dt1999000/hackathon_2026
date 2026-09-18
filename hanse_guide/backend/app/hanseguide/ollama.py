import json
import re

import httpx

from app.core.config import settings
from app.hanseguide.client import ExternalAPIError, http_client

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


async def ollama_chat(
    messages: list[dict[str, str]],
    *,
    format_json: bool = False,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Call Ollama /api/chat and return the assistant message text."""
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload: dict[str, object] = {
        "model": settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if format_json:
        payload["format"] = "json"

    timeout = httpx.Timeout(settings.OLLAMA_TIMEOUT, connect=5.0)
    async with http_client(client, timeout=timeout) as http:
        try:
            response = await http.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise ExternalAPIError("ollama", str(exc)) from exc

    content = data.get("message", {}).get("content") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ExternalAPIError("ollama", "Empty model response")
    return content.strip()


def parse_json_object(text: str) -> dict[str, object]:
    cleaned = _FENCE.sub("", text.strip()).strip()
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload


async def ollama_is_reachable(
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Return True when Ollama answers /api/tags."""
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    timeout = httpx.Timeout(2.0, connect=1.0)
    async with http_client(client, timeout=timeout) as http:
        try:
            response = await http.get(url)
            return response.status_code < 500
        except httpx.HTTPError:
            return False
