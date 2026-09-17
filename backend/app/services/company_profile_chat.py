from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from app.models import CompanyProfileBase, CompanyProfileCreate
from app.services.chat_models import ChatProvider, get_chat_model
from app.services.company_profile_text import render_company_profile_text
from app.services.embeddings import EmbeddingClient

PROFILE_INTAKE_SYSTEM_PROMPT = """
You are Aria, helping a construction/contracting company build a profile
that will later be matched against tender opportunities. Interview the
user conversationally to fill in as much of the following as they're
willing to give — but keep it natural, a few questions at a time, not a
rigid checklist read top to bottom:

- Company basics: name (the only field that's actually required),
  location, founding year, employee count, annual revenue.
- What they do (capabilities) and, just as important, what they
  explicitly DON'T do or can't show experience in (exclusions).
  Certifications/qualifications they hold.
- Where they operate: regions they serve, how far they'll travel from
  their base, and any regions they won't work in.
- Contract size sweet spot (min/max they'd bid) and the value above which
  they'd need a partner rather than bid alone.
- Contractor role (main contractor vs. subcontractor vs. either) and, if
  relevant, the maximum share of a job they can self-perform vs. needing
  to subcontract out.
- Financial guarantee capacity: total limit their bank supports, and how
  much of that is currently committed to other jobs.
- Availability: when they're free from (existing commitments), plus any
  free-text capacity notes.
- Reference projects they can point to as proof of capability.
- Hard constraints ("hardliners") — things that must never happen
  regardless of how good a tender looks, e.g. "never bid rail work",
  "never work outside Germany", "never take on jobs under 3 months
  duration". Ask for these explicitly; they matter a lot later.
- Optionally, invite them to describe their company in their own words,
  informally — a vague, personality-filled answer is completely fine
  here and doesn't need to be translated into anything more precise.

It's fine if answers are vague, informal, or given as an aside — don't
force the user into precise numbers for everything. Company name is the
only hard requirement to save a profile; everything else is best-effort.
If the user says something like "that's everything", "let's finish", or
"save it", treat that as a signal to wrap up rather than continuing to
probe. Be concise and warm, not bureaucratic.
"""


class ProfileExtractionError(Exception):
    """The conversation so far can't be turned into a valid company profile."""


def _to_lc_message(role: str, content: str) -> BaseMessage:
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


def extract_company_profile(
    messages: list[dict[str, str]], provider: ChatProvider
) -> CompanyProfileCreate:
    """Run a one-shot structured extraction over the full conversation so
    far, turning it into a CompanyProfileCreate. Raises
    ProfileExtractionError if the model can't produce a valid profile
    (e.g. the user never gave a company name).
    """
    history: list[BaseMessage] = [SystemMessage(content=PROFILE_INTAKE_SYSTEM_PROMPT)]
    history.extend(_to_lc_message(m["role"], m["content"]) for m in messages)

    llm = get_chat_model(provider)
    structured_llm = llm.with_structured_output(CompanyProfileCreate)
    result = structured_llm.invoke(history)

    try:
        if isinstance(result, CompanyProfileCreate):
            return result
        return CompanyProfileCreate.model_validate(result)
    except ValidationError as e:
        raise ProfileExtractionError(
            "I don't have enough information yet to save a profile — at "
            "minimum I need your company's name."
        ) from e


def embed_company_profile(profile: CompanyProfileBase) -> tuple[str, list[float]]:
    """Render the profile to text and embed it via the shared embedding
    server. Returns (source_text, embedding) for the caller to persist.
    """
    text = render_company_profile_text(profile)
    embedding = EmbeddingClient().embed([text])[0]
    return text, embedding
