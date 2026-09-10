import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import CompaniesPublic, Company, CompanyPublic, Message, Watchlist
from app.services.edgar import EdgarClient
from app.services.ingestion import FilingIngestionService

router = APIRouter(prefix="/watchlist", tags=["watchlist"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=CompaniesPublic)
def list_watchlist(session: SessionDep, current_user: CurrentUser) -> CompaniesPublic:
    companies = session.exec(select(Company).join(Watchlist).where(Watchlist.user_id == current_user.id)).all()
    return CompaniesPublic(data=list(companies), count=len(companies))


@router.post("/{cik}", response_model=CompanyPublic)
def add_to_watchlist(cik: str, session: SessionDep, current_user: CurrentUser) -> Company:
    """
    Adds a company to the current user's watchlist, syncing it from SEC
    EDGAR first if it hasn't been ingested yet. Idempotent.
    """
    service = FilingIngestionService(session)
    try:
        company = service.sync_company(cik)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"SEC EDGAR request failed: {exc}") from exc

    existing = session.exec(
        select(Watchlist).where(Watchlist.user_id == current_user.id, Watchlist.company_id == company.id)
    ).first()
    if existing is None:
        session.add(Watchlist(user_id=current_user.id, company_id=company.id))
        session.commit()
    return company


@router.delete("/{cik}")
def remove_from_watchlist(cik: str, session: SessionDep, current_user: CurrentUser) -> Message:
    cik_padded = EdgarClient.normalize_cik(cik)
    company = session.exec(select(Company).where(Company.cik == cik_padded)).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    entry = session.exec(
        select(Watchlist).where(Watchlist.user_id == current_user.id, Watchlist.company_id == company.id)
    ).first()
    if entry is not None:
        session.delete(entry)
        session.commit()
    return Message(message="Removed from watchlist")
