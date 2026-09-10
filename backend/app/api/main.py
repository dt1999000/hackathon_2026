from fastapi import APIRouter

from app.api.routes import (
    chat,
    companies,
    ingestion,
    items,
    login,
    private,
    tools,
    users,
    utils,
    watchlist,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(chat.router)
api_router.include_router(ingestion.router)
api_router.include_router(companies.router)
api_router.include_router(watchlist.router)


if settings.FASTAPI_ENV == "development":
    api_router.include_router(private.router)
    api_router.include_router(tools.router)
