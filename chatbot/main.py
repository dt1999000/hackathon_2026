from dotenv import load_dotenv
from pydantic import BaseModel
import os
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_agent

from tools import search_tool, wiki_tool, save_tool


load_dotenv()


class ResearchResponse(BaseModel):
    topic: str
    summary: str
    sources: list[str]
    tools_used: list[str]


llm = ChatAnthropic(
    model="claude-sonnet-5",
    default_headers={
        "anthropic-workspace-id": os.getenv("ANTHROPIC_WORKSPACE_ID")
    }
)


tools = [
    search_tool,
    wiki_tool,
    save_tool,
]


system_prompt = """
You are a research assistant that helps generate research papers.

Answer the user's research question thoroughly.

Use the available tools when necessary:
- Use the web search tool for current information.
- Use Wikipedia when useful for general background information.
- Use the save tool when the user asks you to save the research.

Return the final result according to the ResearchResponse schema.
"""


agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=system_prompt,
    response_format=ResearchResponse,
)


query = input("What can I help you research? ")


result = agent.invoke(
    {
        "messages": [
            {
                "role": "user",
                "content": query,
            }
        ]
    }
)


structured_response = result["structured_response"]

print("\n--- Research Result ---")
print(f"Topic: {structured_response.topic}")
print(f"\nSummary:\n{structured_response.summary}")
print(f"\nSources:")
for source in structured_response.sources:
    print(f"- {source}")

print(f"\nTools used:")
for tool in structured_response.tools_used:
    print(f"- {tool}")