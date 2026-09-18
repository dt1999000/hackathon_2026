"""Conversational company-profile intake: an alternative to the manual
onboarding form, reusing the Aria chat infrastructure to interview the
user and extract a CompanyProfileCreate from the transcript.

This revives app.api.routes.company_profile_chat from commit 79eea7ee
("Add chat-driven company profile intake with persisted embedding"),
adapted to the current free-text CompanyProfileBase schema — the old
version targeted the pre-simplification structured/array-field schema
and persisted a separate embedding via a pgvector table, both of which
were dropped when the profile schema was simplified (commit 777ffa64).
Embedding is no longer done here at all: app.agents.bid_fit embeds
profile text on demand at analysis time instead of persisting it.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from app.models import CompanyProfileCreate
from app.services.chat_models import ChatProvider, get_chat_model

PROFILE_INTAKE_SYSTEM_PROMPT = """
You are Aria, helping a construction/contracting company build a profile
that will later be matched against tender opportunities. Interview the
user conversationally to fill in as much of the following as they're
willing to give — but keep it natural, a few questions at a time, not a
rigid checklist read top to bottom:

- Company basics: name (the only field that's actually required), base
  location, founding year, employee count, annual revenue.
- Capabilities — what they do, in their own words (e.g. "road
  construction, sewers and pipelines, earthworks").
- Exclusions — what they explicitly won't or can't do (e.g. "no
  rail-side work", "nothing outside Germany"). Ask them to give these
  one per line if there are several, since each one gets checked
  individually later.
- Certifications or qualifications they hold.
- Geographic reach — regions they serve, how far they'll travel from
  their base, and any regions they won't work in. Free text is fine,
  including conditional nuance (e.g. "mostly Bavaria, but we've
  traveled further for the right client").
- Contract size preferences — the range they normally bid, and what
  happens above or below that (e.g. "below X the overhead isn't worth
  it, above Y we'd need a partner").
- Contractor role — main contractor, subcontractor, or either — and how
  much of a job they self-perform vs. subcontract out.
- Capacity — current commitments, when they're free from, and any
  bonding/guarantee limits their bank supports.
- Reference projects they can point to as proof of capability.
- Hardliners — hard constraints that must never be crossed regardless
  of how good a tender looks (e.g. "never bid rail work", "never work
  outside Germany"). Ask for these explicitly, one per line if there are
  several — they matter a lot later and get checked individually.
- Optionally, invite them to describe their company in their own words,
  informally — a vague, personality-filled answer is completely fine
  here and doesn't need to be tidied up into anything more precise.

It's fine if answers are vague, informal, or given as an aside — these
are free-text fields, not rigid data entry, so don't force the user into
precise numbers or bullet-perfect lists for everything. Company name is
the only hard requirement to save a profile; everything else is
best-effort. If the user says something like "that's everything",
"let's finish", or "save it", treat that as a signal to wrap up rather
than continuing to probe. Be concise and warm, not bureaucratic.
"""


class ProfileExtractionError(Exception):
    """The conversation so far can't be turned into a valid company profile."""


def _to_lc_message(role: str, content: str) -> BaseMessage:
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


def _normalize_per_line_field(value: str | None) -> str | None:
    """`exclusions` is read back one item at a time for retrieval
    (derive_profile_sections's per-line splitting), and `hardliners` —
    while no longer split programmatically anywhere, since
    generate_violations now reads the whole profile at once — is still
    much easier for that same LLM step to reason over cleanly as a
    one-per-line list than as a run-on sentence. Structured-output
    extraction often collapses several distinct items into one
    comma-separated sentence instead of the newline-separated list the
    prompt asks for — a literal newline inside a JSON string value is a
    less natural thing for a model to produce than a comma. Only kicks
    in when there's no newline yet and there are multiple
    comma-separated clauses, so a genuinely prose-style sentence with
    one comma in it is untouched.
    """
    if not value or "\n" in value:
        return value
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return "\n".join(parts) if len(parts) > 1 else value


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

    # Some providers (Gemini) reject a structured-output request whose
    # final turn is an assistant message — it reads as trying to
    # prefill the model's own reply. This happens whenever the user
    # clicks "finish" right after Aria's latest question rather than
    # answering it first; that trailing question carries no new
    # user-supplied information, so it's safe to drop before extraction.
    while len(history) > 1 and isinstance(history[-1], AIMessage):
        history.pop()
    if len(history) <= 1:
        raise ProfileExtractionError(
            "I don't have enough information yet to save a profile — at "
            "minimum I need your company's name."
        )

    llm = get_chat_model(provider)
    structured_llm = llm.with_structured_output(CompanyProfileCreate)
    result = structured_llm.invoke(history)

    try:
        profile = (
            result
            if isinstance(result, CompanyProfileCreate)
            else CompanyProfileCreate.model_validate(result)
        )
    except ValidationError as e:
        raise ProfileExtractionError(
            "I don't have enough information yet to save a profile — at "
            "minimum I need your company's name."
        ) from e

    profile.hardliners = _normalize_per_line_field(profile.hardliners)
    profile.exclusions = _normalize_per_line_field(profile.exclusions)
    return profile
