"""LangGraph agent that flags how well a bid fits a company's hardliners.

Pipeline: reason over the company profile + the user's own notes to derive
a list of hardliners -> load and chunk the bid document -> rank its chunks
by cosine similarity to the hardliners and keep the top-k (this doubles as
the "how similar is this bid to what we do" score) -> feed those top-k
chunks plus the company's profile as context to the LLM, which decides
per hardliner whether the bid actually contradicts it and, if so, whether
a realistic fix exists -> turn the violations into a red/yellow/green
flag, with the similarity score reported alongside it for ranking.

Cosine similarity is used only for retrieval/ranking here, deliberately —
it measures topical closeness, not contradiction (a sentence requiring
rail-side work and one ruling it out score similarly against a "no
rail-side work" hardliner), so it can't be the thing that decides a
hardliner is actually violated. That judgment is the LLM step's job.

`run_bid_fit_analysis` derives hardliners from a stored CompanyProfile.
`run_bid_screen` skips that step for callers who already have a hardliner
list (or want to test one directly, e.g. against
mock_data/agent_input.jsonl) — both share the same retrieval + LLM
verification + scoring nodes.
"""

import json
from typing import Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agents.bid_fit_scoring import BidFitScore, HardlinerViolation, score_bid_fit
from app.models import CompanyProfileBase
from app.services.chat_models import ChatProvider, get_chat_model
from app.services.embeddings import EmbeddingClient
from app.tools.rag.loader.base import SourceContent
from app.tools.rag.loader.json import flatten_json_to_text
from app.tools.rag.registry import get_chunker, get_loader
from app.tools.rag.retrieval import cosine_similarity

DEFAULT_SECTION_MATCH_THRESHOLD = 0.55

FIT_ANALYSIS_PROMPT = """\
You are assessing whether a specific bid fits a company, given its \
hardliners and the bid's own terms.

Hardliners (every one must hold for the bid to be a fit):
{hardliners_block}

Company profile (use this to judge whether a proposed solution is \
actually realistic for this company):
{profile_text}

Retrieved bid terms and metadata (source: {bid_source}):
{context_block}

For EACH hardliner, decide whether the bid, based on the context above, \
ACTUALLY contradicts it — not merely mentions the same topic. A sentence \
requiring rail-side work and one ruling it out both "mention" a "no \
rail-side work" hardliner; only the first is a real contradiction. If the \
context doesn't say enough to tell, assume it does NOT violate the \
hardliner and say so in the reason — absence of evidence isn't a \
violation.

When a hardliner IS violated, propose a solution only if one is \
genuinely realistic given the bid and the company's profile (e.g. \
subcontracting a missing capability, partnering for a certification \
already in progress). The company profile is free text and may itself \
describe a conditional workaround (e.g. "above our usual ceiling we can \
still take it on with a partner") — use that directly if it applies \
rather than treating the violation as unsolvable. Leave the solution \
unset whenever it would be impractical, too slow, too costly, or would \
still leave the hardliner broken — never invent a solution just to have \
one."""


# (label, attribute) for every free-text topic field on CompanyProfileBase,
# shared by format_company_profile and derive_profile_sections so both stay
# in sync with the schema in one place.
_PROFILE_TEXT_SECTIONS: list[tuple[str, str]] = [
    ("Geographic reach", "geographic_reach"),
    ("Contract size preferences", "contract_size"),
    ("Capabilities", "capabilities"),
    ("Exclusions", "exclusions"),
    ("Certifications", "certifications"),
    ("Contractor role", "contractor_role"),
    ("Capacity", "capacity"),
    ("Reference projects", "reference_projects"),
    ("Hardliners", "hardliners"),
    ("In the company's own words", "self_description"),
]


def _split_lines(text: str | None) -> list[str]:
    """Split a free-text field into individual items, one per line —
    matches how a user naturally types a list of hardliners or
    exclusions into a text box."""
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def format_company_profile(profile: CompanyProfileBase) -> str:
    """Full profile dump — basic facts plus every free-text section —
    for the LLM's context (app.agents.bid_fit.generate_violations)."""
    lines = [f"Company: {profile.company_name}"]
    if profile.base_location:
        lines.append(f"Based in: {profile.base_location}")
    if profile.founded_year is not None:
        lines.append(f"Founded: {profile.founded_year}")
    if profile.employee_count is not None:
        lines.append(f"Employees: {profile.employee_count}")
    if profile.annual_revenue_eur is not None:
        lines.append(f"Annual revenue (EUR): {profile.annual_revenue_eur}")
    for label, attr in _PROFILE_TEXT_SECTIONS:
        value = getattr(profile, attr)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def derive_profile_sections(profile: CompanyProfileBase) -> list[str]:
    """Break the company profile's free-text fields into independent
    sections, each checked separately against a bid's chunks in
    `retrieve_bid_context`. Company name/founding year/etc. are omitted
    here — they're facts a bid is never going to "echo", so they'd never
    match anything and would just sit in the denominator dragging the
    similarity score down.
    """
    sections = []
    for label, attr in _PROFILE_TEXT_SECTIONS:
        value = getattr(profile, attr)
        if value:
            sections.append(f"{label}: {value}")
    return sections


def derive_hardliners_from_profile(profile: CompanyProfileBase) -> list[str]:
    """Hardliners come straight from the profile's own free-text
    `hardliners` and `exclusions` fields, one per line — no LLM call, no
    paraphrasing risk.

    Nuanced conditional judgment that doesn't reduce to a flat rule (e.g.
    "we can bring in a partner if the value is a bit over our usual
    ceiling") deliberately isn't pre-compiled into a rigid check here —
    it lives in the other free-text fields (contract_size,
    geographic_reach, capacity) and is handled by `generate_violations`'
    LLM reasoning instead, which can read that nuance directly.
    """
    return [*_split_lines(profile.hardliners), *_split_lines(profile.exclusions)]


class FitAnalysis(BaseModel):
    violations: list[HardlinerViolation]


class BidFitState(TypedDict, total=False):
    profile_text: str
    bid_source: str | None
    bid_content: str | None
    bid_loader: str
    bid_chunker: str
    top_k: int
    match_threshold: float
    hardliners: list[str]
    profile_sections: list[str]
    loader_kwargs: dict[str, Any]
    bid_metadata: dict[str, Any]
    context_chunks: list[str]
    similarity_score: float
    violations: list[HardlinerViolation]
    result: BidFitScore


def _resolve_bid_text(
    bid_source: str | None,
    bid_loader: str,
    bid_content: str | None,
    loader_kwargs: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    """Get the bid's raw text either from `bid_content` given directly in
    the request (no file path or URL needed) or, if that's not given, by
    loading `bid_source` through the usual loader registry.

    `bid_content` is interpreted the same way the matching loader would:
    for bid_loader in ("json", "jsonl") it's parsed as JSON and flattened
    the same way JSONLoader/JSONLLoader do; for anything else (e.g. text
    already extracted from a PDF) it's used as-is.
    """
    if bid_content is not None:
        if bid_loader in ("json", "jsonl"):
            try:
                data = json.loads(bid_content)
            except json.JSONDecodeError as e:
                raise ValueError(f"bid_content is not valid JSON: {e}") from e
            return {"format": bid_loader, "type": type(data).__name__}, flatten_json_to_text(data)
        return {"format": "text"}, bid_content

    if not bid_source:
        raise ValueError("Either bid_source or bid_content must be given")

    loader = get_loader(bid_loader)
    result = loader.load(SourceContent(source=bid_source), **(loader_kwargs or {}))
    return result.metadata, result.content


def retrieve_bid_context(
    bid_source: str | None,
    bid_loader: str,
    bid_chunker: str,
    profile_sections: list[str],
    embedding_client: EmbeddingClient,
    top_k: int,
    match_threshold: float = DEFAULT_SECTION_MATCH_THRESHOLD,
    loader_kwargs: dict[str, Any] | None = None,
    bid_content: str | None = None,
) -> tuple[dict[str, Any], list[str], float]:
    """Load + chunk a bid, then check each of the company's own profile
    sections (capabilities, regions, certifications, self_description,
    ... — see `derive_profile_sections`) against the bid's chunks for its
    single best match. A section counts as matched if that best score
    clears `match_threshold`.

    similarity_score = matched_sections / total_sections: the more of the
    company's own profile sections find a corresponding description in
    the bid, the higher the score. Returns (bid_metadata, matched_chunks,
    similarity_score), where matched_chunks are the bid chunks that
    matched at least one section — highest-scoring first, capped at
    top_k — that's the context handed to the LLM verification step.

    This is retrieval/ranking only: it decides which bid chunks are worth
    showing the LLM, not whether anything is actually violated (cosine
    similarity can't tell "requires X" from "does not require X").

    The bid's content comes from `bid_content` if given directly (no file
    path or URL needed — e.g. paste bid JSON/text straight into the
    request body), otherwise from loading `bid_source` through the usual
    loader registry. `loader_kwargs` is passed through to that loader
    (e.g. record_index/record_id for JSONLLoader) and is ignored when
    `bid_content` is used.
    """
    metadata, text = _resolve_bid_text(bid_source, bid_loader, bid_content, loader_kwargs)
    chunker = get_chunker(bid_chunker)
    chunks = chunker.chunk(text)

    if not chunks or not profile_sections:
        return metadata, [], 0.0

    section_embeddings = embedding_client.embed(profile_sections)
    chunk_embeddings = embedding_client.embed(chunks)

    matched_chunks: dict[str, float] = {}
    matches_found = 0
    for section_embedding in section_embeddings:
        best_score = 0.0
        best_chunk: str | None = None
        for chunk, chunk_embedding in zip(chunks, chunk_embeddings, strict=True):
            score = cosine_similarity(section_embedding, chunk_embedding)
            if score > best_score:
                best_score = score
                best_chunk = chunk

        if best_chunk is not None and best_score >= match_threshold:
            matches_found += 1
            if best_chunk not in matched_chunks or best_score > matched_chunks[best_chunk]:
                matched_chunks[best_chunk] = best_score

    similarity_score = matches_found / len(profile_sections)
    ranked_chunks = sorted(matched_chunks.items(), key=lambda kv: kv[1], reverse=True)
    context_chunks = [chunk for chunk, _ in ranked_chunks[:top_k]]

    return metadata, context_chunks, similarity_score


def generate_violations(
    llm: BaseChatModel,
    hardliners: list[str],
    profile_text: str,
    context_chunks: list[str],
    bid_source: str,
) -> list[HardlinerViolation]:
    """LLM call: given the hardliners, the company's profile, and the
    bid's most relevant (top-k retrieved) content, decide per hardliner
    whether the bid actually contradicts it and whether a realistic fix
    exists. This is the step that turns "topically similar" into
    "genuinely violated or not" — cosine similarity alone can't do this.
    """
    hardliners_block = "\n".join(f"- {h}" for h in hardliners) or "(none identified)"
    context_block = "\n\n".join(context_chunks) or "(no relevant context retrieved)"
    prompt = FIT_ANALYSIS_PROMPT.format(
        hardliners_block=hardliners_block,
        profile_text=profile_text or "(no additional company context provided)",
        bid_source=bid_source,
        context_block=context_block,
    )
    analysis = llm.with_structured_output(FitAnalysis).invoke(prompt)
    assert isinstance(analysis, FitAnalysis)
    return analysis.violations


def _screen_nodes(llm: BaseChatModel, embedding_client: EmbeddingClient) -> dict[str, Any]:
    """Node functions shared by the full-analysis graph and the
    hardliners-given-directly screen graph: retrieve top-k context, ask
    the LLM for violations, then score. Only differ in whether a prior
    `extract_hardliners` node has populated `state["hardliners"]`."""

    def load_bid_context(state: BidFitState) -> dict[str, Any]:
        metadata, context_chunks, similarity_score = retrieve_bid_context(
            bid_source=state.get("bid_source"),
            bid_loader=state["bid_loader"],
            bid_chunker=state["bid_chunker"],
            profile_sections=state["profile_sections"],
            embedding_client=embedding_client,
            top_k=state["top_k"],
            match_threshold=state.get("match_threshold", DEFAULT_SECTION_MATCH_THRESHOLD),
            loader_kwargs=state.get("loader_kwargs"),
            bid_content=state.get("bid_content"),
        )
        return {
            "bid_metadata": metadata,
            "context_chunks": context_chunks,
            "similarity_score": similarity_score,
        }

    def analyze_fit(state: BidFitState) -> dict[str, Any]:
        violations = generate_violations(
            llm=llm,
            hardliners=state["hardliners"],
            profile_text=state.get("profile_text", ""),
            context_chunks=state["context_chunks"],
            bid_source=state.get("bid_source") or "(inline bid content)",
        )
        return {"violations": violations}

    def score_fit(state: BidFitState) -> dict[str, Any]:
        result = score_bid_fit(state["violations"], state["similarity_score"])
        return {"result": result}

    return {
        "load_bid_context": load_bid_context,
        "analyze_fit": analyze_fit,
        "score_fit": score_fit,
    }


def build_bid_fit_graph(
    provider: ChatProvider = "claude",
    embedding_model: str | None = None,
) -> Any:
    """Compile the bid-fit pipeline: retrieve the bid content most similar
    to the company's profile sections, ask the LLM to verify real
    contradictions/solutions against the given hardliners, then score.
    Hardliners themselves are never derived inside the graph — both
    `run_bid_fit_analysis` (from a stored CompanyProfile) and
    `run_bid_screen` (given directly) compute them up front, since
    `derive_hardliners_from_profile` needs no LLM call."""
    llm = get_chat_model(provider)
    embedding_client = EmbeddingClient(model=embedding_model)
    nodes = _screen_nodes(llm, embedding_client)

    graph = StateGraph(BidFitState)
    graph.add_node("load_bid_context", nodes["load_bid_context"])
    graph.add_node("analyze_fit", nodes["analyze_fit"])
    graph.add_node("score_fit", nodes["score_fit"])

    graph.add_edge(START, "load_bid_context")
    graph.add_edge("load_bid_context", "analyze_fit")
    graph.add_edge("analyze_fit", "score_fit")
    graph.add_edge("score_fit", END)

    return graph.compile()


def run_bid_fit_analysis(
    company_profile: CompanyProfileBase,
    bid_loader: str,
    bid_source: str | None = None,
    bid_content: str | None = None,
    bid_chunker: str = "default",
    top_k: int = 5,
    provider: ChatProvider = "claude",
    embedding_model: str | None = None,
    match_threshold: float = DEFAULT_SECTION_MATCH_THRESHOLD,
    record_index: int = 0,
    record_id: str | None = None,
) -> BidFitState:
    """Build hardliners from `company_profile`'s structured fields (no LLM
    call — see `derive_hardliners_from_profile`) and run the bid-fit
    pipeline. Retrieval matches the bid against the profile's own
    descriptive sections (`derive_profile_sections`), not against the
    hardliners. Give the bid either as `bid_content` directly (no file
    path or URL needed) or as `bid_source` (loaded via the registered
    `bid_loader`) — exactly one of the two. `record_index`/`record_id`
    are forwarded to the loader (relevant for bid_loader="jsonl") and
    ignored when `bid_content` is used. Returns the final graph state."""
    graph = build_bid_fit_graph(provider=provider, embedding_model=embedding_model)
    initial_state: BidFitState = {
        "profile_text": format_company_profile(company_profile),
        "profile_sections": derive_profile_sections(company_profile),
        "hardliners": derive_hardliners_from_profile(company_profile),
        "bid_source": bid_source,
        "bid_content": bid_content,
        "bid_loader": bid_loader,
        "bid_chunker": bid_chunker,
        "top_k": top_k,
        "match_threshold": match_threshold,
        "loader_kwargs": {"record_index": record_index, "record_id": record_id},
    }
    final_state = graph.invoke(initial_state)
    return final_state  # type: ignore[return-value]


def run_bid_screen(
    hardliners: list[str],
    bid_loader: str,
    bid_source: str | None = None,
    bid_content: str | None = None,
    bid_chunker: str = "default",
    top_k: int = 5,
    provider: ChatProvider = "claude",
    embedding_model: str | None = None,
    company_context: str = "",
    profile_sections: list[str] | None = None,
    match_threshold: float = DEFAULT_SECTION_MATCH_THRESHOLD,
    record_index: int = 0,
    record_id: str | None = None,
) -> BidFitState:
    """Screen a bid against a hardliner list given directly by the caller
    (no stored CompanyProfile). `profile_sections` are the independent
    descriptive sections retrieval matches against the bid (see
    `retrieve_bid_context`) — pass real ones (capabilities, regions,
    certifications, ...) when available, since they retrieve better than
    LLM-paraphrased hardliner rules; if omitted, falls back to using
    `hardliners` themselves as the sections. `company_context` is
    optional free text used only to judge whether a proposed solution is
    realistic — pass "" if unavailable. Give the bid either as
    `bid_content` directly (no file path or URL needed) or as
    `bid_source` (loaded via the registered `bid_loader`) — exactly one
    of the two. `record_index`/`record_id` are forwarded to the loader
    (relevant for bid_loader="jsonl", e.g. mock_data/agent_input.jsonl)
    and ignored when `bid_content` is used. Returns the final graph
    state."""
    graph = build_bid_fit_graph(provider=provider, embedding_model=embedding_model)
    initial_state: BidFitState = {
        "hardliners": hardliners,
        "profile_sections": profile_sections if profile_sections is not None else hardliners,
        "profile_text": company_context,
        "bid_source": bid_source,
        "bid_content": bid_content,
        "bid_loader": bid_loader,
        "bid_chunker": bid_chunker,
        "top_k": top_k,
        "match_threshold": match_threshold,
        "loader_kwargs": {"record_index": record_index, "record_id": record_id},
    }
    final_state = graph.invoke(initial_state)
    return final_state  # type: ignore[return-value]
