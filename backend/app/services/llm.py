from typing import Any

import httpx

from app.core.config import settings


class LocalLLMClient:
    """Client for the shared Ollama server running on this machine.

    qwen2.5:0.5b is a 0.5B-parameter model and can be unreliable at strict
    structured output (JSON/tool-call formatting) — callers that need
    dependable structured responses should parse leniently or use a larger
    pulled model.
    """

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = base_url or settings.LLM_LOCAL_BASE_URL
        self.model = model or settings.LLM_LOCAL_MODEL

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                **kwargs,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["message"]["content"])
