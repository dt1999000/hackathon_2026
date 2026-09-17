import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.core.config import settings
from app.models import CompanyProfilePublic
from app.services.chat import chat_completion
from app.services.chat_models import ChatProvider
from app.services.company_profile_chat import (
    PROFILE_INTAKE_SYSTEM_PROMPT,
    ProfileExtractionError,
    embed_company_profile,
    extract_company_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/company-profile/chat", tags=["company-profile"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ProfileChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: ChatProvider = "claude"


class ProfileChatResponse(BaseModel):
    content: str


@router.post(
    "/message",
    response_model=ProfileChatResponse,
    dependencies=[Depends(get_current_user)],
)
def send_profile_chat_message(request: ProfileChatRequest) -> ProfileChatResponse:
    """
    Send a message to the company-profile intake assistant.
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
    Extract a company profile from the intake conversation, save it, and
    embed it for later retrieval. Saving the profile always happens if
    extraction succeeds; embedding is best-effort and logged on failure
    rather than failing the request, since it depends on a separate
    embedding server that may not be reachable.
    """
    try:
        profile_in = extract_company_profile(
            messages=[m.model_dump() for m in request.messages],
            provider=request.provider,
        )
    except ProfileExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    profile = crud.upsert_company_profile(
        session=session, owner_id=current_user.id, profile_in=profile_in
    )

    try:
        source_text, embedding = embed_company_profile(profile)
        crud.upsert_company_profile_embedding(
            session=session,
            company_profile_id=profile.id,
            source_text=source_text,
            embedding=embedding,
            embedding_model=settings.LLM_EMBEDDING_MODEL,
        )
    except Exception:
        logger.exception(
            "Failed to embed company profile %s; profile was still saved.",
            profile.id,
        )

    return profile
