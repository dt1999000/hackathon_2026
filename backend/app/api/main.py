from fastapi import APIRouter

from app.api.routes import (
    bid_fit,
    chat,
    company_profile,
    items,
    login,
    private,
    tools,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(chat.router)
api_router.include_router(company_profile.router)
api_router.include_router(bid_fit.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
    api_router.include_router(tools.router)
