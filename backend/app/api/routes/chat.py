from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services.chat import OutputLanguage, chat_completion
from app.services.chat_models import ChatProvider

router = APIRouter(
    prefix="/chat", tags=["chat"], dependencies=[Depends(get_current_user)]
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: ChatProvider = "claude"
    language: OutputLanguage = "en"


class ChatResponse(BaseModel):
    content: str


@router.post("/message", response_model=ChatResponse)
def send_message(request: ChatRequest) -> ChatResponse:
    """
    Send a message to the general-purpose chat assistant (Aria).
    """
    content = chat_completion(
        messages=[m.model_dump() for m in request.messages],
        provider=request.provider,
        language=request.language,
    )
    return ChatResponse(content=content)
