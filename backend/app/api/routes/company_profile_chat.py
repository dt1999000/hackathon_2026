from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import CompanyProfilePublic
from app.services.chat import chat_completion
from app.services.chat_models import ChatProvider
from app.services.company_profile_chat import (
    PROFILE_INTAKE_SYSTEM_PROMPT,
    ProfileExtractionError,
    extract_company_profile,
)

router = APIRouter(
    prefix="/company-profile/chat",
    tags=["company-profile"],
    dependencies=[Depends(get_current_user)],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ProfileChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: ChatProvider = "google"


class ProfileChatResponse(BaseModel):
    content: str


@router.post("/message", response_model=ProfileChatResponse)
def send_profile_chat_message(request: ProfileChatRequest) -> ProfileChatResponse:
    """
    Send a message to the company-profile intake assistant — Aria
    interviewing the user to build their CompanyProfile conversationally
    instead of through the onboarding form (see
    app.services.company_profile_chat).
    """
    content = chat_completion(
        messages=[m.model_dump() for m in request.messages],
        provider=request.provider,
        system_prompt=PROFILE_INTAKE_SYSTEM_PROMPT,
    )
    return ProfileChatResponse(content=content)


@router.post("/finalize", response_model=CompanyProfilePublic)
def finalize_company_profile_chat(
    *, session: SessionDep, current_user: CurrentUser, request: ProfileChatRequest
) -> Any:
    """
    Extract a company profile from the intake conversation and save it —
    creates it if the user has none yet, updates it if they're revising
    an existing one (see crud.upsert_company_profile).
    """
    try:
        profile_in = extract_company_profile(
            messages=[m.model_dump() for m in request.messages],
            provider=request.provider,
        )
    except ProfileExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return crud.upsert_company_profile(
        session=session, owner_id=current_user.id, profile_in=profile_in
    )
