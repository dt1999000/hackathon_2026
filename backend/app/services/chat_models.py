from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.core.config import settings

ChatProvider = Literal["claude", "local"]


def get_chat_model(provider: ChatProvider) -> BaseChatModel:
    """Return a LangChain chat model for the requested provider.

    "claude" requires ANTHROPIC_API_KEY to be set. "local" talks to the
    shared Ollama server configured via LLM_LOCAL_BASE_URL/LLM_LOCAL_MODEL.
    """
    if provider == "claude":
        default_headers = (
            {"anthropic-workspace-id": settings.ANTHROPIC_WORKSPACE_ID}
            if settings.ANTHROPIC_WORKSPACE_ID
            else None
        )
        return ChatAnthropic(  # type: ignore[call-arg]
            model=settings.LLM_CLAUDE_MODEL,
            default_headers=default_headers,
        )
    return ChatOllama(model=settings.LLM_LOCAL_MODEL, base_url=settings.LLM_LOCAL_BASE_URL)
