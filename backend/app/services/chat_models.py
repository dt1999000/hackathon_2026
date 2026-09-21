from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

from app.core.config import settings

ChatProvider = Literal["claude", "local", "google"]


def get_chat_model(provider: ChatProvider) -> BaseChatModel:
    """Return a LangChain chat model for the requested provider.

    "claude" requires ANTHROPIC_API_KEY to be set. "google" requires
    GOOGLE_API_KEY to be set and talks to Gemini (LLM_GEMINI_MODEL). "local"
    talks to the shared Ollama server configured via
    LLM_LOCAL_BASE_URL/LLM_LOCAL_MODEL.
    """
    if provider == "claude":
        default_headers = (
            {"anthropic-workspace-id": settings.ANTHROPIC_WORKSPACE_ID}
            if settings.ANTHROPIC_WORKSPACE_ID
            else None
        )
        kwargs: dict[str, object] = {
            "model": settings.LLM_CLAUDE_MODEL,
            "default_headers": default_headers,
        }
        if settings.ANTHROPIC_API_KEY:
            kwargs["api_key"] = settings.ANTHROPIC_API_KEY
        return ChatAnthropic(**kwargs)  # type: ignore[arg-type]
    if provider == "google":
        return ChatGoogleGenerativeAI(model=settings.LLM_GEMINI_MODEL)
    return ChatOllama(model=settings.LLM_LOCAL_MODEL, base_url=settings.LLM_LOCAL_BASE_URL)
