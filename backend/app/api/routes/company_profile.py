from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import CompanyProfile, CompanyProfileCreate, CompanyProfilePublic, Message

router = APIRouter(prefix="/company-profile", tags=["company-profile"])


@router.get("/me", response_model=CompanyProfilePublic)
def read_company_profile_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Get the current user's company profile.
    """
    profile = session.exec(
        select(CompanyProfile).where(CompanyProfile.owner_id == current_user.id)
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return profile


@router.post("/me", response_model=CompanyProfilePublic)
def create_company_profile_me(
    *, session: SessionDep, current_user: CurrentUser, profile_in: CompanyProfileCreate
) -> Any:
    """
    Create the current user's company profile.
    """
    existing = session.exec(
        select(CompanyProfile).where(CompanyProfile.owner_id == current_user.id)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Company profile already exists")
    profile = CompanyProfile.model_validate(
        profile_in, update={"owner_id": current_user.id}
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.delete("/me", response_model=Message)
def delete_company_profile_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Delete the current user's company profile, so POST /me can be used
    to set it again (POST 409s while a profile already exists).
    """
    profile = session.exec(
        select(CompanyProfile).where(CompanyProfile.owner_id == current_user.id)
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Company profile not found")
    session.delete(profile)
    session.commit()
    return Message(message="Company profile deleted successfully")
