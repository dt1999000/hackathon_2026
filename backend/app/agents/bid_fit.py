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
from app.tools.rag.loader.json import flatten_json_to_text, load_json_data
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


# Fields whose value is a list of independent items, one per line (the
# same "one per line" convention hardliners/exclusions already use in
# derive_hardliners_from_profile) — each line becomes its own retrieval
# section instead of being blended into one query. A blended multi-item
# query (e.g. "Capabilities: Road construction, sewers and pipelines,
# earthworks...") can't tell a caller which specific item a bid chunk
# actually matched, and a chunk that matches none of the listed items
# can still drift toward a decent score just from sharing the sentence's
# general construction/domain vocabulary — splitting gives each item
# its own, comparable, single-topic query instead.
_PER_LINE_PROFILE_SECTIONS = {"capabilities", "exclusions", "reference_projects"}


def derive_profile_sections(profile: CompanyProfileBase) -> list[str]:
    """Break the company profile's free-text fields into independent
    sections, each checked separately against a bid's chunks in
    `retrieve_bid_context`. Company name/founding year/etc. are omitted
    here — they're facts a bid is never going to "echo", so they'd never
    match anything and would just sit in the denominator dragging the
    similarity score down. `_PER_LINE_PROFILE_SECTIONS` fields are split
    one item per line rather than kept as one blended section.
    """
    sections = []
    for label, attr in _PROFILE_TEXT_SECTIONS:
        value = getattr(profile, attr)
        if not value:
            continue
        if attr in _PER_LINE_PROFILE_SECTIONS:
            sections.extend(f"{label}: {line}" for line in _split_lines(value))
        else:
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
    # Not consulted by the graph's load_bid_context node anymore — it
    # uses rerank_bid_context (an LLM judgment) instead of a cosine
    # match_threshold cutoff. Kept on the state/request models only so
    # existing callers of run_bid_fit_analysis/run_bid_screen don't
    # break; still the real cutoff for retrieve_bid_context, used
    # directly (not through the graph) by /bid-fit/retrieve.
    match_threshold: float
    hardliners: list[str]
    profile_sections: list[str]
    loader_kwargs: dict[str, Any]
    bid_metadata: dict[str, Any]
    context_chunks: list[str]
    similarity_score: float
    violations: list[HardlinerViolation]
    result: BidFitScore


# Fields worth keeping, and their label, from this app's "contract
# notice" bid schema (schemaVersion/provenance/notice/buyer/procedure/
# classification/placeOfPerformance/value/duration/submission/
# selectionCriteria/awardCriteria/qualificationRequirementCodes/
# procurementDocuments/documentContents — see mock_data/bids/*.json).
# Deliberately excludes provenance, notice (identifiers, type codes,
# timestamps), classification's CPV codes, and submission's logistics
# fields: none of that is prose, but each still gets embedded as its
# own chunk when the whole JSON is flattened wholesale, and short
# structurally-generic JSON fragments like `"noticeTypeCode":
# "cn-standard"` turned out to score AS HIGH OR HIGHER against a
# company profile section's embedding as genuinely relevant content
# (see retrieve_bid_context's docstring) — they land in a generic
# "procurement notice" region of embedding space close to almost any
# query, drowning out real matches rather than merely not helping.
def _extract_bid_notice_text(data: Any) -> str | None:
    """Render only the substantive natural-language content of this
    app's bid-notice JSON schema — title, description, place of
    performance, value/duration when actually given, selection/award
    criteria, qualification requirements, document descriptions, and
    the extracted document text itself. Returns None if `data` doesn't
    look like this schema (missing "procedure"/"documentContents"), so
    callers fall back to flatten_json_to_text for other JSON shapes."""
    if not isinstance(data, dict):
        return None
    procedure = data.get("procedure")
    document_contents = data.get("documentContents")
    if not isinstance(procedure, dict) or not isinstance(document_contents, list):
        return None

    parts: list[str] = []

    if title := procedure.get("title"):
        parts.append(f"Title: {title}")
    if description := procedure.get("description"):
        parts.append(f"Description: {description}")

    if buyer_names := (data.get("buyer") or {}).get("names"):
        parts.append("Buyer: " + ", ".join(buyer_names))

    for place in data.get("placeOfPerformance") or []:
        bits = [
            place.get(k)
            for k in ("street", "additionalStreet", "postcode", "city", "country")
            if place.get(k)
        ]
        if bits:
            parts.append("Place of performance: " + ", ".join(bits))

    value = data.get("value") or {}
    if value.get("estimatedValue") is not None:
        parts.append(f"Estimated value: {value['estimatedValue']} {value.get('currency', '')}".strip())

    duration = data.get("duration") or {}
    duration_bits = [f"{k}: {duration[k]}" for k in ("startDate", "endDate", "measure") if duration.get(k)]
    if duration_bits:
        parts.append("Duration: " + ", ".join(duration_bits))

    for criterion in data.get("selectionCriteria") or []:
        text = criterion if isinstance(criterion, str) else json.dumps(criterion, ensure_ascii=False)
        parts.append(f"Selection criterion: {text}")

    if award_types := (data.get("awardCriteria") or {}).get("types"):
        parts.append("Award criteria: " + ", ".join(str(t) for t in award_types))

    for code in data.get("qualificationRequirementCodes") or []:
        parts.append(f"Qualification requirement: {code}")

    for link in (data.get("procurementDocuments") or {}).get("links") or []:
        if link_description := link.get("description"):
            parts.append(f"Document: {link_description}")

    for doc in document_contents:
        if text := doc.get("text"):
            parts.append(text)

    return "\n\n".join(parts) if parts else None


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
    for bid_loader in ("json", "jsonl") it's parsed as JSON; for anything
    else (e.g. text already extracted from a PDF) it's used as-is. JSON
    bids are rendered via `_extract_bid_notice_text` (only the
    substantive fields of this app's bid-notice schema) when the shape
    matches, falling back to the generic flatten_json_to_text otherwise
    (e.g. mock_data/agent_input.jsonl records with a different shape).
    """
    if bid_content is not None:
        if bid_loader in ("json", "jsonl"):
            try:
                data = json.loads(bid_content)
            except json.JSONDecodeError as e:
                raise ValueError(f"bid_content is not valid JSON: {e}") from e
            text = _extract_bid_notice_text(data) or flatten_json_to_text(data)
            return {"format": bid_loader, "type": type(data).__name__}, text
        return {"format": "text"}, bid_content

    if not bid_source:
        raise ValueError("Either bid_source or bid_content must be given")

    if bid_loader == "json":
        data = load_json_data(SourceContent(source=bid_source))
        text = _extract_bid_notice_text(data) or flatten_json_to_text(data)
        metadata = {
            "format": "json",
            "type": type(data).__name__,
            "size": len(data) if isinstance(data, list | dict) else 1,
        }
        return metadata, text

    loader = get_loader(bid_loader)
    result = loader.load(SourceContent(source=bid_source), **(loader_kwargs or {}))
    return result.metadata, result.content


def _load_and_chunk_bid(
    bid_source: str | None,
    bid_loader: str,
    bid_chunker: str,
    bid_content: str | None,
    loader_kwargs: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Shared by `retrieve_bid_context` (pure cosine-threshold retrieval)
    and `rerank_bid_context`'s candidate-pool step: resolve the bid's
    text and split it into chunks, without deciding relevance yet."""
    metadata, text = _resolve_bid_text(bid_source, bid_loader, bid_content, loader_kwargs)
    chunker = get_chunker(bid_chunker)
    return metadata, chunker.chunk(text)


def _rank_chunks_per_section(
    profile_sections: list[str],
    chunks: list[str],
    embedding_client: EmbeddingClient,
    top_n: int,
) -> list[list[tuple[str, float]]]:
    """For each profile section, rank every chunk by cosine similarity
    and keep its top_n (chunk, score) pairs, highest first. Pure
    retrieval/ranking — cosine similarity measures topical closeness,
    not genuine relevance (see this module's top docstring), so this is
    a candidate pool for a caller to filter further: a match_threshold
    cutoff on the single best candidate (`retrieve_bid_context`) or an
    LLM judging the top few (`rerank_bid_context`) — not a relevance
    judgment on its own.
    """
    if not chunks or not profile_sections:
        return [[] for _ in profile_sections]

    section_embeddings = embedding_client.embed(profile_sections)
    chunk_embeddings = embedding_client.embed(chunks)

    per_section: list[list[tuple[str, float]]] = []
    for section_embedding in section_embeddings:
        scored = sorted(
            (
                (chunk, cosine_similarity(section_embedding, chunk_embedding))
                for chunk, chunk_embedding in zip(chunks, chunk_embeddings, strict=True)
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        per_section.append(scored[:top_n])
    return per_section


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
    similarity can't tell "requires X" from "does not require X") — nor
    can it reliably tell "genuinely about X" from "generic same-domain
    text that happens to mention X-adjacent words" (see
    `rerank_bid_context`, which the full bid-fit pipeline uses instead of
    this cosine-threshold decision; this function stays as-is so
    /bid-fit/retrieve keeps testing the raw bi-encoder step in isolation).

    The bid's content comes from `bid_content` if given directly (no file
    path or URL needed — e.g. paste bid JSON/text straight into the
    request body), otherwise from loading `bid_source` through the usual
    loader registry. `loader_kwargs` is passed through to that loader
    (e.g. record_index/record_id for JSONLLoader) and is ignored when
    `bid_content` is used.
    """
    metadata, chunks = _load_and_chunk_bid(bid_source, bid_loader, bid_chunker, bid_content, loader_kwargs)
    if not chunks or not profile_sections:
        return metadata, [], 0.0

    per_section = _rank_chunks_per_section(profile_sections, chunks, embedding_client, top_n=1)

    matched_chunks: dict[str, float] = {}
    matches_found = 0
    for candidates in per_section:
        if not candidates:
            continue
        best_chunk, best_score = candidates[0]
        if best_score >= match_threshold:
            matches_found += 1
            if best_chunk not in matched_chunks or best_score > matched_chunks[best_chunk]:
                matched_chunks[best_chunk] = best_score

    similarity_score = matches_found / len(profile_sections)
    ranked_chunks = sorted(matched_chunks.items(), key=lambda kv: kv[1], reverse=True)
    context_chunks = [chunk for chunk, _ in ranked_chunks[:top_k]]

    return metadata, context_chunks, similarity_score


DEFAULT_RERANK_CANDIDATE_POOL = 2

RERANK_PROMPT = """\
You are filtering bid-retrieval candidates before they're used to check \
a company's profile sections against a bid. For each section below, \
a couple of bid-text excerpts were retrieved by embedding similarity — \
but embedding similarity mostly reflects "same general topic/domain" \
(construction, procurement administration, etc.), not genuine \
relevance. Generic contract-administration boilerplate routinely \
scores as high as, or higher than, an excerpt that actually describes \
what the section is about.

For EACH section, decide fast: does either candidate excerpt \
genuinely, specifically relate to what the section describes — not \
just share general procurement/construction vocabulary? If yes, pick \
the single BEST one, copied verbatim, character for character. \
Otherwise set matched to false and leave chunk unset immediately —  \
"no genuine match" is the common, expected, default case, not a \
failure to justify. Do not explain your reasoning, just decide.

{sections_block}"""


class RerankedMatch(BaseModel):
    section: str
    matched: bool
    chunk: str | None = None


class RerankResult(BaseModel):
    matches: list[RerankedMatch]


def _format_rerank_sections_block(
    profile_sections: list[str], candidates_per_section: list[list[tuple[str, float]]]
) -> str:
    blocks = []
    for label, candidates in zip(profile_sections, candidates_per_section):
        if not candidates:
            continue
        candidate_lines = "\n".join(f'  - "{chunk}"' for chunk, _ in candidates)
        blocks.append(f'Section: "{label}"\nCandidate excerpts:\n{candidate_lines}')
    return "\n\n".join(blocks)


def rerank_bid_context(
    llm: BaseChatModel,
    profile_sections: list[str],
    candidates_per_section: list[list[tuple[str, float]]],
    top_k: int,
) -> tuple[list[str], float]:
    """LLM-based reranking of `_rank_chunks_per_section`'s bi-encoder
    candidates: cosine similarity alone can't distinguish "same domain"
    from "genuinely relevant" (see this module's top docstring), so a
    match_threshold on raw cosine scores — what `retrieve_bid_context`
    does — lets generic same-domain boilerplate through as often as
    real matches. This instead asks the LLM to look at each section's
    small candidate pool and decide which, if any, genuinely relates to
    that section, replacing the pure-cosine match/no-match decision.

    Returns (context_chunks, similarity_score) in the same shape as
    `retrieve_bid_context`, so the bid-fit graph's `load_bid_context`
    node can use this instead without changing anything downstream.
    """
    sections_block = _format_rerank_sections_block(profile_sections, candidates_per_section)
    if not sections_block:
        return [], 0.0

    result = llm.with_structured_output(RerankResult).invoke(
        RERANK_PROMPT.format(sections_block=sections_block)
    )
    assert isinstance(result, RerankResult)

    candidates_by_section = dict(zip(profile_sections, candidates_per_section))
    matched_chunks: dict[str, float] = {}
    matches_found = 0
    for match in result.matches:
        if not match.matched or not match.chunk:
            continue
        matches_found += 1
        # Look the chunk back up in its section's candidate pool to
        # recover its original cosine score, used only to rank
        # context_chunks below (the LLM is asked to return it verbatim,
        # but falls back to 0.0 rather than erroring if it paraphrased
        # slightly — matches_found/similarity_score are unaffected).
        score = next(
            (s for chunk, s in candidates_by_section.get(match.section, []) if chunk == match.chunk),
            0.0,
        )
        if match.chunk not in matched_chunks or score > matched_chunks[match.chunk]:
            matched_chunks[match.chunk] = score

    similarity_score = matches_found / len(profile_sections) if profile_sections else 0.0
    ranked_chunks = sorted(matched_chunks.items(), key=lambda kv: kv[1], reverse=True)
    context_chunks = [chunk for chunk, _ in ranked_chunks[:top_k]]

    return context_chunks, similarity_score


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
        profile_sections = state["profile_sections"]
        metadata, chunks = _load_and_chunk_bid(
            bid_source=state.get("bid_source"),
            bid_loader=state["bid_loader"],
            bid_chunker=state["bid_chunker"],
            bid_content=state.get("bid_content"),
            loader_kwargs=state.get("loader_kwargs"),
        )
        if not chunks or not profile_sections:
            return {"bid_metadata": metadata, "context_chunks": [], "similarity_score": 0.0}

        candidates_per_section = _rank_chunks_per_section(
            profile_sections, chunks, embedding_client, top_n=DEFAULT_RERANK_CANDIDATE_POOL
        )
        context_chunks, similarity_score = rerank_bid_context(
            llm=llm,
            profile_sections=profile_sections,
            candidates_per_section=candidates_per_section,
            top_k=state["top_k"],
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
