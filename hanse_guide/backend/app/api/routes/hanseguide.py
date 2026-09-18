from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.hanseguide.agent import run_agent
from app.hanseguide.client import ExternalAPIError, LocationNotFoundError
from app.hanseguide.geocode import geocode_location
from app.hanseguide.models import (
    ChatRequest,
    ChatResponse,
    GeocodeResult,
    HealthResponse,
    PlacesQueryResponse,
    PlaceType,
    WeatherQueryResponse,
)
from app.hanseguide.ollama import ollama_is_reachable
from app.hanseguide.places import search_nearby_places
from app.hanseguide.weather import get_weather as fetch_weather

router = APIRouter(prefix="/hanseguide", tags=["hanseguide"])


def _raise_hanseguide_error(exc: Exception) -> NoReturn:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, LocationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    if isinstance(exc, ExternalAPIError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    raise exc


async def _resolve_origin(
    location: str,
    latitude: float | None,
    longitude: float | None,
) -> GeocodeResult:
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide both latitude and longitude, or neither.",
        )
    if latitude is not None and longitude is not None:
        return GeocodeResult(
            display_name=location,
            latitude=latitude,
            longitude=longitude,
        )
    return await geocode_location(location)


@router.post("/chat")
async def chat(body: ChatRequest) -> ChatResponse:
    try:
        return await run_agent(body.message)
    except Exception as exc:
        _raise_hanseguide_error(exc)


@router.get("/places")
async def get_places(
    place_type: PlaceType = "cafe",
    location: str = "Hamburg Hbf",
    latitude: float | None = None,
    longitude: float | None = None,
    radius: int = Query(default=1500, ge=200, le=5000),
    limit: int = Query(default=10, ge=1, le=25),
) -> PlacesQueryResponse:
    try:
        origin = await _resolve_origin(location, latitude, longitude)
        places = await search_nearby_places(
            origin.latitude,
            origin.longitude,
            place_type,
            radius=radius,
        )
    except Exception as exc:
        _raise_hanseguide_error(exc)
    return PlacesQueryResponse(
        origin=origin,
        place_type=place_type,
        places=places[:limit],
    )


@router.get("/weather")
async def get_weather(
    location: str = "Hamburg Hbf",
    latitude: float | None = None,
    longitude: float | None = None,
    date: str | None = None,
) -> WeatherQueryResponse:
    try:
        origin = await _resolve_origin(location, latitude, longitude)
        weather = await fetch_weather(
            origin.latitude,
            origin.longitude,
            date=date,
        )
    except Exception as exc:
        _raise_hanseguide_error(exc)
    return WeatherQueryResponse(origin=origin, weather=weather)


@router.get("/health")
async def hanseguide_health() -> HealthResponse:
    ollama = await ollama_is_reachable()
    return HealthResponse(
        status="ok" if ollama else "degraded",
        project=settings.PROJECT_NAME,
        database=settings.DATABASE_URL is not None,
        ollama=ollama,
        ollama_model=settings.OLLAMA_MODEL,
    )
