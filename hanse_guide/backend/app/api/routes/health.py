from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "database": settings.DATABASE_URL is not None,
    }
