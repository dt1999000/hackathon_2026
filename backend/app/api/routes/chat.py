from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services.chat import chat_completion
from app.services.chat_models import ChatProvider
from app.services.research_agent import (
    ResearchAgentError,
    ResearchResponse,
    run_research_agent,
)

router = APIRouter(
    prefix="/chat", tags=["chat"], dependencies=[Depends(get_current_user)]
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: ChatProvider = "claude"


class ChatResponse(BaseModel):
    content: str


class ResearchRequest(BaseModel):
    query: str
    provider: ChatProvider = "claude"


@router.post("/message", response_model=ChatResponse)
def send_message(request: ChatRequest) -> ChatResponse:
    """
    Send a message to the general-purpose chat assistant (Aria).
    """
    content = chat_completion(
        messages=[m.model_dump() for m in request.messages],
        provider=request.provider,
    )
    return ChatResponse(content=content)


@router.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest) -> ResearchResponse:
    """
    Run the research agent (web search, Wikipedia, save-to-file tools).
    """
    try:
        return run_research_agent(query=request.query, provider=request.provider)
    except ResearchAgentError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
