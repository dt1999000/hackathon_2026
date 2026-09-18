from typing import Literal

from pydantic import BaseModel, Field, field_validator

PlaceType = Literal["cafe", "library", "park"]
IntentPlaceType = Literal["cafe", "library", "park", "mixed"]
IntentSource = Literal["ollama", "keyword_fallback"]

_PLACE_TYPE_ALIASES = {
    "coffee": "cafe",
    "café": "cafe",
    "cafes": "cafe",
    "cafés": "cafe",
    "libraries": "library",
    "parks": "park",
    "garden": "park",
    "gardens": "park",
}


class GeocodeResult(BaseModel):
    display_name: str
    latitude: float
    longitude: float


class Weather(BaseModel):
    temperature: float
    precipitation_probability: int | None = None
    description: str
    weather_code: int | None = None


class Place(BaseModel):
    name: str
    address: str | None = None
    latitude: float
    longitude: float
    place_type: PlaceType
    distance_meters: int | None = None
    osm_id: int | None = None


class RouteResult(BaseModel):
    distance_meters: int
    duration_seconds: int | None = None
    source: Literal["osrm", "haversine"] = Field(
        description="osrm when the routing API succeeds, otherwise haversine"
    )


class Intent(BaseModel):
    location: str = "Hamburg Hbf"
    place_type: IntentPlaceType = "cafe"
    activity: str | None = None
    date: str | None = None
    time: str | None = None
    radius: int = 1500
    preferences: list[str] = Field(default_factory=list)
    include_park_if_dry: bool = False

    @field_validator("location", mode="before")
    @classmethod
    def _normalize_location(cls, value: object) -> str:
        if value is None or str(value).strip() == "":
            return "Hamburg Hbf"
        return str(value).strip()

    @field_validator("place_type", mode="before")
    @classmethod
    def _normalize_place_type(cls, value: object) -> str:
        if value is None or str(value).strip() == "":
            return "cafe"
        key = str(value).strip().lower()
        return _PLACE_TYPE_ALIASES.get(key, key)

    @field_validator("preferences", mode="before")
    @classmethod
    def _normalize_preferences(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator("radius", mode="before")
    @classmethod
    def _normalize_radius(cls, value: object) -> int:
        if value is None or value == "":
            return 1500
        try:
            radius = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1500
        return min(max(radius, 200), 5000)


class PlaceRecommendation(BaseModel):
    name: str
    address: str | None = None
    distance_meters: int | None = None
    latitude: float
    longitude: float
    reason: str
    place_type: PlaceType


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    answer: str
    intent: Intent
    weather: Weather | None = None
    places: list[PlaceRecommendation]
    tools_used: list[str]


class PlacesQueryResponse(BaseModel):
    origin: GeocodeResult
    place_type: PlaceType
    places: list[Place]


class WeatherQueryResponse(BaseModel):
    origin: GeocodeResult
    weather: Weather


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    project: str
    database: bool
    ollama: bool
    ollama_model: str
