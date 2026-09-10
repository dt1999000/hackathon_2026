from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import SessionDep, get_current_user
from app.services.company_directory import CompanyDirectoryEntry, search_companies
from app.services.timeline import CompanyTimeline, get_company_timeline

router = APIRouter(prefix="/companies", tags=["companies"], dependencies=[Depends(get_current_user)])


@router.get("/search", response_model=list[CompanyDirectoryEntry])
def search(q: str) -> list[CompanyDirectoryEntry]:
    """Search SEC's full company directory by name or ticker (not limited to companies already ingested)."""
    return search_companies(q)


@router.get("/{cik}/timeline", response_model=CompanyTimeline)
def get_timeline(cik: str, session: SessionDep) -> CompanyTimeline:
    """
    Every filing ingested for a company, newest first, with structured
    signals and any narrative changes already computed for it. 404s if the
    company hasn't been synced yet.
    """
    timeline = get_company_timeline(session, cik)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Company not found. Add it to a watchlist first.")
    return timeline
