from typing import Any, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlmodel import select

from app.agents.bid_fit import (
    DEFAULT_SECTION_MATCH_THRESHOLD,
    derive_hardliners_from_profile,
    derive_profile_sections,
    generate_violations,
    merge_hardliners_with_notes,
    retrieve_bid_context,
    run_bid_fit_analysis,
    run_bid_screen,
)
from app.agents.bid_fit_scoring import (
    BidFitScore,
    HardlinerViolation,
    rank_bid_fits,
    score_bid_fit,
)
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import CompanyProfile
from app.services.chat_models import ChatProvider, get_chat_model
from app.services.embeddings import EmbeddingClient

router = APIRouter(
    prefix="/bid-fit", tags=["bid-fit"], dependencies=[Depends(get_current_user)]
)


class _BidInputFields(BaseModel):
    """Give the bid either as `bid_content` directly in the request body
    (no file path or URL needed — paste bid JSON/text straight in) or as
    `bid_source` (a path or URL, loaded via the registered `bid_loader`,
    e.g. bid_loader="jsonl" + bid_source pointing at
    mock_data/agent_input.jsonl). Exactly one of the two."""

    bid_source: str | None = None
    bid_content: str | None = None

    @model_validator(mode="after")
    def _check_exactly_one_bid_input(self) -> Self:
        if bool(self.bid_source) == bool(self.bid_content):
            raise ValueError("Give exactly one of bid_source or bid_content")
        return self


def _get_company_profile(session: SessionDep, current_user: CurrentUser) -> CompanyProfile:
    profile = session.exec(
        select(CompanyProfile).where(CompanyProfile.owner_id == current_user.id)
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return profile


# --- Composite endpoints: the full pipelines -------------------------------


class BidFitRequest(_BidInputFields):
    user_notes: str = ""
    bid_loader: str
    bid_chunker: str = "default"
    top_k: int = 5
    provider: ChatProvider = "claude"
    embedding_model: str | None = None
    match_threshold: float = DEFAULT_SECTION_MATCH_THRESHOLD
    record_index: int = 0
    record_id: str | None = None


class BidFitResponse(BaseModel):
    hardliners: list[str]
    violations: list[HardlinerViolation]
    flag: str
    similarity_score: float
    hard_blockers: list[str]
    soft_issues: list[str]


def _to_bid_fit_response(final_state: dict[str, Any]) -> BidFitResponse:
    result: BidFitScore = final_state["result"]
    return BidFitResponse(
        hardliners=final_state["hardliners"],
        violations=final_state["violations"],
        flag=result.flag,
        similarity_score=result.similarity_score,
        hard_blockers=result.hard_blockers,
        soft_issues=result.soft_issues,
    )


@router.post("/analyze", response_model=BidFitResponse)
def analyze_bid_fit(
    *, session: SessionDep, current_user: CurrentUser, request: BidFitRequest
) -> Any:
    """
    Full pipeline: derive hardliners from the current user's company
    profile + `user_notes`, then check each of the profile's own
    descriptive sections (capabilities, regions, certifications, ...)
    against the bid for its best-matching content — the more sections
    that find a match, the higher `similarity_score` — and hand the
    matched context to the LLM to verify real contradictions and
    solutions, then flag red/yellow/green (see
    app.agents.bid_fit_scoring). `similarity_score` ranks bids sharing a
    flag, it does not decide the flag itself.
    """
    profile = _get_company_profile(session, current_user)
    final_state = run_bid_fit_analysis(
        company_profile=profile,
        user_notes=request.user_notes,
        bid_source=request.bid_source,
        bid_content=request.bid_content,
        bid_loader=request.bid_loader,
        bid_chunker=request.bid_chunker,
        top_k=request.top_k,
        provider=request.provider,
        embedding_model=request.embedding_model,
        match_threshold=request.match_threshold,
        record_index=request.record_index,
        record_id=request.record_id,
    )
    return _to_bid_fit_response(final_state)


class BidScreenRequest(_BidInputFields):
    hardliners: list[str]
    bid_loader: str
    bid_chunker: str = "default"
    top_k: int = 5
    provider: ChatProvider = "claude"
    embedding_model: str | None = None
    company_context: str = ""
    # Independent descriptive sections (capabilities, regions,
    # certifications, ...) to match against the bid for retrieval. Falls
    # back to using `hardliners` themselves if omitted — real profile
    # sections generally retrieve better than paraphrased hardliner rules.
    profile_sections: list[str] | None = None
    match_threshold: float = DEFAULT_SECTION_MATCH_THRESHOLD
    # JSONLLoader-specific: which record to load out of a .jsonl file of
    # many bids (e.g. mock_data/agent_input.jsonl). Ignored by other
    # loaders.
    record_index: int = 0
    record_id: str | None = None


@router.post("/screen", response_model=BidFitResponse)
def screen_bid(request: BidScreenRequest) -> Any:
    """
    Same pipeline as /analyze, but for hardliners you already have (no
    stored company profile needed) — e.g. testing directly against
    mock_data/agent_input.jsonl via bid_loader="jsonl".
    """
    final_state = run_bid_screen(
        hardliners=request.hardliners,
        bid_source=request.bid_source,
        bid_content=request.bid_content,
        bid_loader=request.bid_loader,
        bid_chunker=request.bid_chunker,
        top_k=request.top_k,
        provider=request.provider,
        embedding_model=request.embedding_model,
        company_context=request.company_context,
        profile_sections=request.profile_sections,
        match_threshold=request.match_threshold,
        record_index=request.record_index,
        record_id=request.record_id,
    )
    return _to_bid_fit_response(final_state)


# --- Per-stage endpoints: each core function, for isolated testing --------


class ExtractHardlinersRequest(BaseModel):
    user_notes: str = ""
    provider: ChatProvider = "claude"


class ExtractHardlinersResponse(BaseModel):
    hardliners: list[str]


@router.post("/extract-hardliners", response_model=ExtractHardlinersResponse)
def extract_hardliners(
    *, session: SessionDep, current_user: CurrentUser, request: ExtractHardlinersRequest
) -> Any:
    """
    Stage 1 alone: build hardliners from the current user's company
    profile's own structured fields (custom_hardliners,
    explicit_exclusions, contract value range, ... — see
    app.agents.bid_fit.derive_hardliners_from_profile). No LLM call
    unless `user_notes` is non-empty, in which case it's merged in via
    the LLM (add what's new, let notes override/sharpen conflicts). No
    bid involved.
    """
    profile = _get_company_profile(session, current_user)
    base_hardliners = derive_hardliners_from_profile(profile)
    if not request.user_notes.strip():
        return ExtractHardlinersResponse(hardliners=base_hardliners)

    llm = get_chat_model(request.provider)
    hardliners = merge_hardliners_with_notes(llm, base_hardliners, request.user_notes)
    return ExtractHardlinersResponse(hardliners=hardliners)


class ProfileSectionsResponse(BaseModel):
    profile_sections: list[str]


@router.get("/profile-sections", response_model=ProfileSectionsResponse)
def profile_sections(*, session: SessionDep, current_user: CurrentUser) -> Any:
    """
    What /bid-fit/retrieve (and /analyze internally) would match against
    a bid: the current user's company profile broken into independent
    descriptive sections. No LLM/embedding call.
    """
    profile = _get_company_profile(session, current_user)
    return ProfileSectionsResponse(profile_sections=derive_profile_sections(profile))


class RetrieveBidContextRequest(_BidInputFields):
    profile_sections: list[str]
    bid_loader: str
    bid_chunker: str = "default"
    top_k: int = 5
    match_threshold: float = DEFAULT_SECTION_MATCH_THRESHOLD
    embedding_model: str | None = None
    record_index: int = 0
    record_id: str | None = None


class RetrieveBidContextResponse(BaseModel):
    bid_metadata: dict[str, Any]
    context_chunks: list[str]
    similarity_score: float


@router.post("/retrieve", response_model=RetrieveBidContextResponse)
def retrieve(request: RetrieveBidContextRequest) -> Any:
    """
    Stage 2 alone: load + chunk a bid (JSON, JSONL, PDF, or any other
    registered loader), then check each of `profile_sections` (e.g. the
    company's capabilities, regions, certifications, self_description —
    see app.agents.bid_fit.derive_profile_sections) against the bid's
    chunks for its single best match. similarity_score = the fraction of
    sections that found a match above `match_threshold` — the more
    matches found, the higher the score. No LLM call — this is
    retrieval/ranking only, not a fit judgment.
    """
    try:
        metadata, context_chunks, similarity_score = retrieve_bid_context(
            bid_source=request.bid_source,
            bid_content=request.bid_content,
            bid_loader=request.bid_loader,
            bid_chunker=request.bid_chunker,
            profile_sections=request.profile_sections,
            embedding_client=EmbeddingClient(model=request.embedding_model),
            top_k=request.top_k,
            match_threshold=request.match_threshold,
            loader_kwargs={"record_index": request.record_index, "record_id": request.record_id},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RetrieveBidContextResponse(
        bid_metadata=metadata, context_chunks=context_chunks, similarity_score=similarity_score
    )


class GenerateViolationsRequest(BaseModel):
    hardliners: list[str]
    context_chunks: list[str]
    profile_text: str = ""
    bid_source: str = ""
    provider: ChatProvider = "claude"


class GenerateViolationsResponse(BaseModel):
    violations: list[HardlinerViolation]


@router.post("/generate-violations", response_model=GenerateViolationsResponse)
def generate_violations_endpoint(request: GenerateViolationsRequest) -> Any:
    """
    Stage 3 alone: given hardliners, retrieved bid context (e.g. from
    /bid-fit/retrieve), and optional company context, ask the LLM which
    hardliners are ACTUALLY contradicted (not just topically related) and
    whether a realistic solution exists.
    """
    llm = get_chat_model(request.provider)
    violations = generate_violations(
        llm=llm,
        hardliners=request.hardliners,
        profile_text=request.profile_text,
        context_chunks=request.context_chunks,
        bid_source=request.bid_source,
    )
    return GenerateViolationsResponse(violations=violations)


class ScoreBidFitRequest(BaseModel):
    violations: list[HardlinerViolation]
    similarity_score: float = 0.0


@router.post("/score", response_model=BidFitScore)
def score(request: ScoreBidFitRequest) -> Any:
    """
    Stage 4 alone: turn a violations list + similarity score into the
    red/yellow/green flag. Pure function, no LLM/embedding calls — see
    app.agents.bid_fit_scoring for the asymmetric weighting rationale.
    """
    return score_bid_fit(request.violations, request.similarity_score)


class RankBidFitsRequest(BaseModel):
    results: list[BidFitScore]


class RankBidFitsResponse(BaseModel):
    ranked: list[BidFitScore]


@router.post("/rank", response_model=RankBidFitsResponse)
def rank(request: RankBidFitsRequest) -> Any:
    """
    Rank multiple already-scored bids best-first: flag first (green beats
    yellow beats red, regardless of similarity_score on either side),
    then similarity_score (higher first) breaks ties within the same
    flag. Pure function, no LLM/embedding calls.
    """
    return RankBidFitsResponse(ranked=rank_bid_fits(request.results))
