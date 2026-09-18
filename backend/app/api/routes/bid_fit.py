import concurrent.futures
import json
import logging
import uuid
from typing import Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import func
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
    _FLAG_RANK,
    BidFitScore,
    HardlinerViolation,
    rank_bid_fits,
    score_bid_fit,
)
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import Bid, CompanyProfile, Contract
from app.services.chat_models import ChatProvider, get_chat_model
from app.services.embeddings import EmbeddingClient

# Max concurrent analyze_one() calls in analyze_bids — each one is a
# handful of LLM/embedding calls, so a thread per row (fine for a
# handful of mock_data/bids/*.json demo rows) turns into hundreds of
# simultaneous API calls once Contract rows from a real scrape are in
# the mix, which just trips rate limits across the board instead of
# actually going faster.
MAX_ANALYZE_WORKERS = 16

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


class _AnalyzableItem(BaseModel):
    id: uuid.UUID
    title: str | None
    notice_identifier: str | None
    bid_content: str


def _bid_items(session: SessionDep) -> list[_AnalyzableItem]:
    bids = session.exec(select(Bid)).all()
    return [
        _AnalyzableItem(
            id=b.id, title=b.title, notice_identifier=b.notice_identifier, bid_content=b.raw_json
        )
        for b in bids
    ]


def _recent_contracts(session: SessionDep, limit: int) -> list[Contract]:
    """The `limit` most recently *found* contracts — ordered by when the
    scrape pipeline's import wrote the row (created_at), not the
    tender's own publication_date, since "last found" is about our
    scrape, not the buyer's notice. Applied as a SQL LIMIT, not a
    fetch-everything-then-slice in Python — the contract table holds
    every scraped notice (currently in the hundreds) and only keeps
    growing."""
    return list(
        session.exec(
            select(Contract).order_by(Contract.created_at.desc()).limit(limit)
        ).all()
    )


def _contract_items(session: SessionDep, limit: int) -> list[_AnalyzableItem]:
    # Contract rows come straight from the DB — populated directly by
    # scripts/import_contracts.py off the scrape pipeline's output, no
    # file copied into mock_data/bids/ needed. raw_json is already a
    # parsed dict (a proper JSON column), so it's re-serialized here to
    # match bid_content's "JSON text" contract, the same shape
    # bid_loader="json" already knows how to flatten.
    return [
        _AnalyzableItem(
            id=c.id,
            title=c.procedure_title,
            notice_identifier=c.notice_identifier,
            bid_content=json.dumps(c.raw_json, ensure_ascii=False),
        )
        for c in _recent_contracts(session, limit)
    ]


@router.post("/analyze-bids", response_model=AnalyzeBidsResponse)
def analyze_bids(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider: ChatProvider = "google",
    top_n: int = 8,
    source: Literal["bids", "contracts", "all"] = "all",
    limit: int = 20,
) -> Any:
    """
    Dashboard "Analyze" action: run the full /analyze pipeline (see
    analyze_bid_fit) against bids for the current user's company
    profile, then rank best-first the same way /bid-fit/rank does (flag
    first, similarity_score breaks ties) and return the top `top_n`.

    `source` picks where those bids come from: "bids" is the `bid` table
    (POST /bids/load, from mock_data/bids/*.json — a fixed handful of
    demo rows, never capped), "contracts" is the `contract` table
    (populated directly by the scrape pipeline + scripts/import_contracts.py
    — queried here as-is, no file copy step involved), "all" (default)
    combines both.

    `limit` caps how many *contracts* get pulled and actually analyzed —
    the `limit` most recently found (see `_recent_contracts`), not an
    arbitrary DB-order slice. Separate from `top_n`, which only limits
    the *output* after everything already got analyzed and ranked. This
    matters because the contract table holds every scraped notice
    (currently in the hundreds) and keeps growing — analyzing all of it
    on every dashboard click would mean hundreds of concurrent
    LLM/embedding calls per request. Raise it deliberately, not by
    leaving it uncapped. GET /bid-fit/contracts with the same `limit`
    shows exactly which contracts this will analyze.

    Runs each item's analysis concurrently, capped at
    MAX_ANALYZE_WORKERS — every analysis is a handful of independent
    LLM/embedding calls, so one thread per item is fine for a handful of
    demo bids but floods the LLM/embedding APIs with hundreds of
    simultaneous requests once real scraped contracts are in the mix. A
    single item's analysis failing (e.g. a transient LLM/embedding
    error) is logged and that item is dropped from the results rather
    than failing the whole batch.
    """
    profile = _get_company_profile(session, current_user)
    items: list[_AnalyzableItem] = []
    if source in ("bids", "all"):
        items.extend(_bid_items(session))
    if source in ("contracts", "all"):
        items.extend(_contract_items(session, limit=limit))
    if not items:
        return AnalyzeBidsResponse(results=[])

    def analyze_one(item: _AnalyzableItem) -> BidMatchResult | None:
        try:
            final_state = run_bid_fit_analysis(
                company_profile=profile,
                bid_content=item.bid_content,
                bid_loader="json",
                provider=provider,
            )
        except Exception:
            logger.exception(f"Bid analysis failed for {item.id} ({item.notice_identifier})")
            return None

        result: BidFitScore = final_state["result"]
        return BidMatchResult(
            bid_id=item.id,
            title=item.title,
            notice_identifier=item.notice_identifier,
            hardliners=final_state["hardliners"],
            violations=final_state["violations"],
            flag=result.flag,
            similarity_score=result.similarity_score,
            hard_blockers=result.hard_blockers,
            soft_issues=result.soft_issues,
        )

    max_workers = min(len(items), MAX_ANALYZE_WORKERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(analyze_one, item) for item in items]
        results = [r for r in (f.result() for f in futures) if r is not None]

    ranked = sorted(results, key=lambda r: (_FLAG_RANK[r.flag], -r.similarity_score))
    return AnalyzeBidsResponse(results=ranked[:top_n])


class ContractSummary(BaseModel):
    id: uuid.UUID
    title: str | None
    notice_identifier: str
    publication_date: str | None
    estimated_value: float | None
    currency: str | None
    place_of_performance: list
    source_system: str


class ListContractsResponse(BaseModel):
    contracts: list[ContractSummary]
    total_in_database: int


@router.get("/contracts", response_model=ListContractsResponse)
def list_contracts(*, session: SessionDep, limit: int = 20) -> Any:
    """
    Dashboard "Load contracts" action: the `limit` most recently found
    contracts (see `_recent_contracts`) out of the `contract` table —
    populated directly by the scrape pipeline + scripts/import_contracts.py,
    queried here as-is, no file copy step involved. `total_in_database` is
    the full row count, so the UI can show "20 of 614" rather than
    implying these are all there are. Calling POST /bid-fit/analyze-bids
    with the same `limit` analyzes exactly this set (plus the `bid` table
    rows, unless source="contracts").
    """
    total_in_database = session.exec(select(func.count()).select_from(Contract)).one()
    contracts = _recent_contracts(session, limit)
    return ListContractsResponse(
        contracts=[
            ContractSummary(
                id=c.id,
                title=c.procedure_title,
                notice_identifier=c.notice_identifier,
                publication_date=c.publication_date,
                estimated_value=c.estimated_value,
                currency=c.currency,
                place_of_performance=c.place_of_performance,
                source_system=c.source_system,
            )
            for c in contracts
        ],
        total_in_database=total_in_database,
    )


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
