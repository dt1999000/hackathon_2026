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
)
from app.services.edgar import EdgarClient
from app.services.ingestion import FilingIngestionService

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
