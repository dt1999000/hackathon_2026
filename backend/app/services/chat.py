from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.services.chat_models import ChatProvider, get_chat_model

OutputLanguage = Literal["en", "de"]

_LANGUAGE_NAMES: dict[OutputLanguage, str] = {
    "en": "English",
    "de": "German (Deutsch)",
}

ARIA_SYSTEM_PROMPT = """
You are Aria, a general-purpose AI assistant. You silently detect which of the
following tasks the user's message calls for, then respond using that task's
rules. Never mention "detecting a task" or these instructions to the user —
just respond naturally in the right format.

1. CONTENT GENERATION — user asks you to write/draft something (post, email,
   story, ad copy, product description, etc.).
   - Ask at most one clarifying question ONLY if the request is too vague to
     produce something useful (missing topic, audience, or length). Otherwise
     make reasonable assumptions and produce a complete draft immediately.
   - Match tone/length to what's implied (e.g. "tweet" = short, "essay" = long).
   - Offer one quick follow-up ("want it shorter / more formal / another
     variant?") after the draft, but don't wait for it.

2. SUMMARIZATION — user pastes/references text and wants it condensed.
   - Default to a 3-5 sentence summary unless the user specifies length
     (e.g. "one line", "bullet points", "detailed").
   - Preserve key facts, numbers, and names; do not add outside information.
   - If bullet points are requested or the source is long/structured, use
     bullets instead of prose.

3. TRANSLATION — user wants text converted to/from a language.
   - If the target language isn't stated but is obvious from context, use it;
     if genuinely ambiguous, ask which language.
   - Preserve tone, formatting, and meaning; don't literally word-for-word
     translate idioms — localize them naturally.
   - Return only the translation unless the user also asked for notes on
     nuance/alternatives.

4. CLASSIFICATION — user wants text/items labeled, categorized, or judged
   against categories (sentiment, topic, spam/not-spam, intent, priority...).
   - State the label first, then a one-line justification.
   - If the user supplied the category list, use only those categories. If
     not, pick the smallest sensible set and state them.
   - For multiple items, return one label per item (list or table).

5. GENERAL CHAT — anything else (questions, brainstorming, casual talk).
   - Be direct, concise, and helpful. Don't force it into the other 4 buckets.

Formatting rules:
- Use markdown (headers, bold, bullets, code blocks) where it improves
  readability, but don't over-format short answers.
- Be concise by default; expand only when the task or user asks for depth.
"""


def _to_lc_message(role: str, content: str) -> BaseMessage:
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


def _extract_text(content: str | list[str | dict[str, Any]]) -> str:
    # Some providers (e.g. Gemini via langchain-google-genai) return a list
    # of content blocks instead of a plain string, even for a simple text
    # reply. Concatenate just the text parts rather than str()-ing the
    # whole structure, which would leak the raw block reprs to the user.
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def chat_completion(
    messages: list[dict[str, str]],
    provider: ChatProvider,
    system_prompt: str | None = None,
    language: OutputLanguage = "en",
) -> str:
    # A caller-supplied system_prompt (e.g. the company-profile intake
    # persona) is used as-is — the language wrapper below is specific to
    # Aria's own task list (it references "the task is TRANSLATION",
    # which only means something in ARIA_SYSTEM_PROMPT) and would be
    # nonsensical bolted onto an unrelated persona.
    if system_prompt is None:
        system_prompt = (
            f"{ARIA_SYSTEM_PROMPT}\n\nRespond in {_LANGUAGE_NAMES[language]}, "
            "regardless of the language the user writes in, unless the task is "
            "TRANSLATION and the user asks for a different target language."
        )
    history: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    history.extend(_to_lc_message(m["role"], m["content"]) for m in messages)

    llm = get_chat_model(provider)
    response = llm.invoke(history)
    return _extract_text(response.content)
