"""Research-agent tools: web search, Wikipedia lookup, and save-to-file."""

from datetime import datetime

from langchain_community.tools import DuckDuckGoSearchRun, WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_core.tools import tool


@tool
def save_to_txt(data: str, filename: str = "research_output.txt") -> str:
    """Save research data to a text file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    formatted_text = f"--- Research Output ---\nTimestamp: {timestamp}\n\n{data}\n\n"

    with open(filename, "a", encoding="utf-8") as f:
        f.write(formatted_text)

    return f"Data successfully saved to {filename}"


search_tool = DuckDuckGoSearchRun()

wiki_tool = WikipediaQueryRun(
    api_wrapper=WikipediaAPIWrapper(  # type: ignore[call-arg]
        top_k_results=1, doc_content_chars_max=100
    )
)

save_tool = save_to_txt
