import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Message,
    Profile,
    ProfileCreate,
    ProfilePublic,
    ProfilesPublic,
    ProfileUpdate,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/", response_model=ProfilesPublic)
def read_profiles(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve company profiles.
    """

    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Profile)
        count = session.exec(count_statement).one()
        statement = (
            select(Profile)
            .order_by(col(Profile.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        profiles = session.exec(statement).all()
    else:
        count_statement = (
            select(func.count())
            .select_from(Profile)
            .where(Profile.owner_id == current_user.id)
        )
        count = session.exec(count_statement).one()
        statement = (
            select(Profile)
            .where(Profile.owner_id == current_user.id)
            .order_by(col(Profile.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        profiles = session.exec(statement).all()

    profiles_public = [ProfilePublic.model_validate(profile) for profile in profiles]
    return ProfilesPublic(data=profiles_public, count=count)


@router.get("/{id}", response_model=ProfilePublic)
def read_profile(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get a company profile by ID.
    """
    profile = session.get(Profile, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not current_user.is_superuser and (profile.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return profile


@router.post("/", response_model=ProfilePublic)
def create_profile(
    *, session: SessionDep, current_user: CurrentUser, profile_in: ProfileCreate
) -> Any:
    """
    Create a new company profile. Every field is optional.
    """
    profile = Profile.model_validate(profile_in, update={"owner_id": current_user.id})
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.put("/{id}", response_model=ProfilePublic)
def update_profile(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    profile_in: ProfileUpdate,
) -> Any:
    """
    Update a company profile.
    """
    profile = session.get(Profile, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not current_user.is_superuser and (profile.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    update_dict = profile_in.model_dump(exclude_unset=True)
    profile.sqlmodel_update(update_dict)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.delete("/{id}")
def delete_profile(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete a company profile.
    """
    profile = session.get(Profile, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if not current_user.is_superuser and (profile.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    session.delete(profile)
    session.commit()
    return Message(message="Profile deleted successfully")
