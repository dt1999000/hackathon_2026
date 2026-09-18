import concurrent.futures
import logging
import uuid
from typing import Any, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlmodel import select

from app.agents.bid_fit import (
    DEFAULT_SECTION_MATCH_THRESHOLD,
    derive_profile_sections,
    generate_violations,
    retrieve_bid_context,
    run_bid_fit_analysis,
    run_bid_screen,
)
from app.agents.bid_fit_scoring import (
    DEFAULT_EXAMPLES_PER_FLAG,
    BidFitScore,
    HardlinerViolation,
    pick_flag_examples,
    rank_bid_fits,
    score_bid_fit,
)
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import Bid, CompanyProfile
from app.services.chat_models import ChatProvider, get_chat_model
from app.services.embeddings import EmbeddingClient
from app.services.language import OutputLanguage

logger = logging.getLogger(__name__)

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
    bid_loader: str
    bid_chunker: str = "default"
    top_k: int = 5
    provider: ChatProvider = "claude"
    embedding_model: str | None = None
    match_threshold: float = DEFAULT_SECTION_MATCH_THRESHOLD
    record_index: int = 0
    record_id: str | None = None
    language: OutputLanguage = "de"


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
    Full pipeline: check each of the current user's company profile's
    own descriptive sections (capabilities, regions, certifications,
    ...) against the bid for its best-matching content — the more
    sections that find a match, the higher `similarity_score` — and hand
    the matched context plus the whole profile to the LLM to find real
    contradictions and solutions (there's no separate pre-extracted
    hardliner checklist; it reads hardliners/exclusions and every other
    stated constraint straight out of the profile), then flag
    red/yellow/green (see app.agents.bid_fit_scoring). `similarity_score`
    ranks bids sharing a flag, it does not decide the flag itself.
    """
    profile = _get_company_profile(session, current_user)
    final_state = run_bid_fit_analysis(
        company_profile=profile,
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
        language=request.language,
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
    language: OutputLanguage = "de"


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
        language=request.language,
    )
    return _to_bid_fit_response(final_state)


class BidMatchResult(BaseModel):
    bid_id: uuid.UUID
    title: str | None = None
    notice_identifier: str | None = None
    hardliners: list[str]
    violations: list[HardlinerViolation]
    flag: str
    similarity_score: float
    hard_blockers: list[str]
    soft_issues: list[str]


class AnalyzeBidsResponse(BaseModel):
    results: list[BidMatchResult]


@router.post("/analyze-bids", response_model=AnalyzeBidsResponse)
def analyze_bids(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider: ChatProvider = "claude",
    per_flag: int = DEFAULT_EXAMPLES_PER_FLAG,
    language: OutputLanguage = "de",
) -> Any:
    """
    Dashboard "Analyze" action: run the full /analyze pipeline (see
    analyze_bid_fit) against every bid loaded via POST /bids/load, for
    the current user's company profile, then return a mix of outcomes:
    up to `per_flag` good matches (green), warnings (yellow), and
    hardlined bids (red), highest similarity within each flag. Runs each
    bid's analysis concurrently — every one is a handful of independent
    LLM/embedding calls, so doing them sequentially would take minutes
    even for a handful of bids. A single bid's analysis failing (e.g. a
    transient LLM/embedding error) is logged and that bid is dropped
    from the results rather than failing the whole batch.
    """
    profile = _get_company_profile(session, current_user)
    bids = session.exec(select(Bid)).all()
    if not bids:
        return AnalyzeBidsResponse(results=[])

    def analyze_one(bid: Bid) -> BidMatchResult | None:
        try:
            final_state = run_bid_fit_analysis(
                company_profile=profile,
                bid_content=bid.raw_json,
                bid_loader="json",
                provider=provider,
                language=language,
            )
        except Exception:
            logger.exception(f"Bid analysis failed for bid {bid.id} ({bid.source_file})")
            return None

        result: BidFitScore = final_state["result"]
        return BidMatchResult(
            bid_id=bid.id,
            title=bid.title,
            notice_identifier=bid.notice_identifier,
            hardliners=final_state["hardliners"],
            violations=final_state["violations"],
            flag=result.flag,
            similarity_score=result.similarity_score,
            hard_blockers=result.hard_blockers,
            soft_issues=result.soft_issues,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(bids))) as executor:
        futures = [executor.submit(analyze_one, bid) for bid in bids]
        results = [r for r in (f.result() for f in futures) if r is not None]

    return AnalyzeBidsResponse(results=pick_flag_examples(results, per_flag=per_flag))


# --- Per-stage endpoints: each core function, for isolated testing --------


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
    Stage 1 alone: load + chunk a bid (JSON, JSONL, PDF, or any other
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
    context_chunks: list[str]
    profile_text: str = ""
    bid_source: str = ""
    provider: ChatProvider = "claude"
    language: OutputLanguage = "de"


class GenerateViolationsResponse(BaseModel):
    violations: list[HardlinerViolation]


@router.post("/generate-violations", response_model=GenerateViolationsResponse)
def generate_violations_endpoint(request: GenerateViolationsRequest) -> Any:
    """
    Stage 2 alone: given the company's whole profile text and retrieved
    bid context (e.g. from /bid-fit/retrieve), ask the LLM to find every
    genuine contradiction (not just topically related mentions) and
    whether a realistic solution exists for each — there's no separate
    pre-extracted hardliner list; the LLM reads hardliners/exclusions
    and every other stated constraint straight out of `profile_text`.
    """
    llm = get_chat_model(request.provider)
    violations = generate_violations(
        llm=llm,
        profile_text=request.profile_text,
        context_chunks=request.context_chunks,
        bid_source=request.bid_source,
        language=request.language,
    )
    return GenerateViolationsResponse(violations=violations)


class ScoreBidFitRequest(BaseModel):
    violations: list[HardlinerViolation]
    similarity_score: float = 0.0


@router.post("/score", response_model=BidFitScore)
def score(request: ScoreBidFitRequest) -> Any:
    """
    Stage 3 alone: turn a violations list + similarity score into the
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
