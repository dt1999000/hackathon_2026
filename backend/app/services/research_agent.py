from typing import Any, cast

from langchain.agents import create_agent
from pydantic import BaseModel

from app.services.chat_models import ChatProvider, get_chat_model
from app.tools.research import save_tool, search_tool, wiki_tool

RESEARCH_SYSTEM_PROMPT = """
You are a research assistant that helps generate research papers.

Answer the user's research question thoroughly.

Use the available tools when necessary:
- Use the web search tool for current information.
- Use Wikipedia when useful for general background information.
- Use the save tool when the user asks you to save the research.

Return the final result according to the ResearchResponse schema.
"""


class ResearchResponse(BaseModel):
    topic: str
    summary: str
    sources: list[str]
    tools_used: list[str]


class ResearchAgentError(Exception):
    """Raised when the agent doesn't produce a valid structured response.

    Small/local models are unreliable at the tool-calling and structured
    output this agent requires; this is most likely to happen with
    provider="local" rather than a bug in the agent itself.
    """


def run_research_agent(query: str, provider: ChatProvider) -> ResearchResponse:
    agent = create_agent(
        model=get_chat_model(provider),
        tools=[search_tool, wiki_tool, save_tool],
        system_prompt=RESEARCH_SYSTEM_PROMPT,
        response_format=ResearchResponse,
    )

    result = cast(
        dict[str, Any],
        agent.invoke({"messages": [{"role": "user", "content": query}]}),
    )
    structured_response = result.get("structured_response")
    if structured_response is None:
        raise ResearchAgentError(
            f"The '{provider}' model did not return a valid structured response. "
            "Small/local models often can't reliably follow this agent's "
            "tool-calling and structured-output requirements — try provider='claude'."
        )
    return cast(ResearchResponse, structured_response)
