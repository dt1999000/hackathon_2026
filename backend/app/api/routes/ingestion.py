import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, select

from app.api.deps import SessionDep, get_current_user
from app.models import (
    Company,
    CompanyPublic,
    Filing,
    FilingsPublic,
    FinancialFact,
    FinancialFactsPublic,
    NarrativeChange,
    NarrativeChangesPublic,
)
from app.services.edgar import EdgarClient
from app.services.ingestion import FilingIngestionService
from app.services.narrative_diff import SectionType, diff_narrative_section
from app.services.signals import (
    DilutionTrend,
    FilingSignals,
    GrossMarginTrend,
    get_dilution_trend,
    get_filing_signals,
    get_gross_margin_trend,
)

router = APIRouter(prefix="/ingestion", tags=["ingestion"], dependencies=[Depends(get_current_user)])


@router.post("/companies/{cik}/sync", response_model=CompanyPublic)
def sync_company(cik: str, session: SessionDep) -> Company:
    """
    Fetch a company's filing history and structured XBRL facts from SEC
    EDGAR and upsert them. Safe to re-run; only new filings/facts are added.
    """
    service = FilingIngestionService(session)
    try:
        return service.sync_company(cik)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"SEC EDGAR request failed: {exc}") from exc


@router.get("/companies/{cik}/filings", response_model=FilingsPublic)
def list_filings(cik: str, session: SessionDep) -> FilingsPublic:
    """List filings ingested so far for a company, oldest first."""
    cik_padded = EdgarClient.normalize_cik(cik)
    company = session.exec(select(Company).where(Company.cik == cik_padded)).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found. Sync it first.")
    filings = session.exec(
        select(Filing).where(Filing.company_id == company.id).order_by(col(Filing.filing_date))
    ).all()
    return FilingsPublic(data=list(filings), count=len(filings))


@router.get("/filings/{filing_id}/facts", response_model=FinancialFactsPublic)
def list_facts(filing_id: uuid.UUID, session: SessionDep) -> FinancialFactsPublic:
    """List structured financial facts ingested for a single filing."""
    facts = session.exec(select(FinancialFact).where(FinancialFact.filing_id == filing_id)).all()
    return FinancialFactsPublic(data=list(facts), count=len(facts))


@router.get("/filings/{filing_id}/signals", response_model=FilingSignals)
def get_signals(filing_id: uuid.UUID, session: SessionDep) -> FilingSignals:
    """
    Debt/liquidity and capital-expenditure change signals for a filing,
    derived from structured facts against the prior filing of the same
    form_type (Filing.previous_filing_id). Empty/null fields mean the
    filing has no previous_filing_id or the concept wasn't reported.
    """
    filing = session.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found")
    return get_filing_signals(session, filing)


@router.get("/filings/{filing_id}/dilution-trend", response_model=DilutionTrend)
def get_dilution_trend_route(filing_id: uuid.UUID, session: SessionDep) -> DilutionTrend:
    """
    Share count and stock-based-compensation trend across up to 3 consecutive
    filings of the same form_type, ending at this filing (exact year-over-year
    for 10-Ks, quarter-over-quarter for 10-Qs, via Filing.previous_filing_id).
    """
    filing = session.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found")
    return get_dilution_trend(session, filing)


@router.get("/filings/{filing_id}/gross-margin-trend", response_model=GrossMarginTrend)
def get_gross_margin_trend_route(filing_id: uuid.UUID, session: SessionDep) -> GrossMarginTrend:
    """
    Revenue and gross-margin trend across up to 3 consecutive filings of the
    same form_type, ending at this filing. Flags any period where margin
    compressed while revenue still grew.
    """
    filing = session.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found")
    return get_gross_margin_trend(session, filing)


@router.post("/filings/{filing_id}/narrative-diff", response_model=NarrativeChangesPublic)
def compute_narrative_diff(filing_id: uuid.UUID, section_type: SectionType, session: SessionDep) -> NarrativeChangesPublic:
    """
    Diff a filing's Risk Factors or Legal Proceedings section against the
    prior filing of the same form_type: fetches both documents, extracts
    the section, chunks and embeds it, matches chunks bidirectionally, and
    asks the LLM to characterize anything that isn't near-identical.
    Persists and returns the changes found. Safe to re-run — re-running
    replaces the previous analysis for this exact (filing, section) pair
    rather than accumulating duplicate rows next to it.
    """
    filing = session.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found")
    try:
        changes = diff_narrative_section(session, filing, section_type)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"SEC EDGAR request failed: {exc}") from exc
    return NarrativeChangesPublic(data=list(changes), count=len(changes))


@router.get("/filings/{filing_id}/narrative-changes", response_model=NarrativeChangesPublic)
def list_narrative_changes(filing_id: uuid.UUID, session: SessionDep) -> NarrativeChangesPublic:
    """List narrative changes already computed (via narrative-diff) for a filing."""
    changes = session.exec(select(NarrativeChange).where(NarrativeChange.filing_id == filing_id)).all()
    return NarrativeChangesPublic(data=list(changes), count=len(changes))
