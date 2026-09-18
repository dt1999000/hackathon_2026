import httpx
import pytest
from fastapi.testclient import TestClient

from app.hanseguide.client import ExternalAPIError, LocationNotFoundError
from app.hanseguide.models import GeocodeResult, Place, Weather
from app.main import app


def test_places_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_geocode(_location: str, **_kwargs: object) -> GeocodeResult:
        return GeocodeResult(
            display_name="Hamburg Hbf",
            latitude=53.5528,
            longitude=10.0066,
        )

    async def fake_places(
        _lat: float,
        _lon: float,
        _place_type: str,
        **_kwargs: object,
    ) -> list[Place]:
        return [
            Place(
                name="Zentralbibliothek",
                address="Hühnerposten 1, Hamburg",
                latitude=53.5498,
                longitude=10.0061,
                place_type="library",
                distance_meters=450,
            )
        ]

    monkeypatch.setattr("app.api.routes.hanseguide.geocode_location", fake_geocode)
    monkeypatch.setattr(
        "app.api.routes.hanseguide.search_nearby_places", fake_places
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/hanseguide/places",
        params={"place_type": "library", "location": "Hamburg Hbf"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["origin"]["latitude"] == pytest.approx(53.5528)
    assert body["places"][0]["name"] == "Zentralbibliothek"
    assert body["place_type"] == "library"


def test_places_endpoint_requires_both_coordinates() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/hanseguide/places",
        params={"latitude": 53.55},
    )
    assert response.status_code == 400


def test_places_endpoint_uses_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_places(*_args: object, **_kwargs: object) -> list[Place]:
        return []

    monkeypatch.setattr(
        "app.api.routes.hanseguide.search_nearby_places", fake_places
    )
    client = TestClient(app)
    response = client.get(
        "/api/v1/hanseguide/places",
        params={"latitude": 53.55, "longitude": 10.0, "place_type": "cafe"},
    )
    assert response.status_code == 200
    assert response.json()["origin"]["latitude"] == pytest.approx(53.55)


def test_places_endpoint_maps_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_geocode(_location: str, **_kwargs: object) -> GeocodeResult:
        raise LocationNotFoundError("Atlantis")

    monkeypatch.setattr("app.api.routes.hanseguide.geocode_location", fake_geocode)
    client = TestClient(app)
    response = client.get(
        "/api/v1/hanseguide/places",
        params={"location": "Atlantis"},
    )
    assert response.status_code == 404


def test_weather_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_geocode(_location: str, **_kwargs: object) -> GeocodeResult:
        return GeocodeResult(
            display_name="Hamburg Hbf",
            latitude=53.5528,
            longitude=10.0066,
        )

    async def fake_weather(*_args: object, **_kwargs: object) -> Weather:
        return Weather(
            temperature=18.0,
            precipitation_probability=20,
            description="Cloudy",
        )

    monkeypatch.setattr("app.api.routes.hanseguide.geocode_location", fake_geocode)
    monkeypatch.setattr("app.api.routes.hanseguide.fetch_weather", fake_weather)
    client = TestClient(app)
    response = client.get(
        "/api/v1/hanseguide/weather",
        params={"location": "Hamburg Hbf"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["weather"]["description"] == "Cloudy"
    assert body["weather"]["temperature"] == pytest.approx(18.0)


def test_weather_endpoint_maps_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_geocode(_location: str, **_kwargs: object) -> GeocodeResult:
        return GeocodeResult(
            display_name="Hamburg Hbf",
            latitude=53.5528,
            longitude=10.0066,
        )

    async def fake_weather(*_args: object, **_kwargs: object) -> Weather:
        raise ExternalAPIError("open-meteo", "down")

    monkeypatch.setattr("app.api.routes.hanseguide.geocode_location", fake_geocode)
    monkeypatch.setattr("app.api.routes.hanseguide.fetch_weather", fake_weather)
    client = TestClient(app)
    response = client.get("/api/v1/hanseguide/weather")
    assert response.status_code == 502


def test_hanseguide_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_reachable(**_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(
        "app.api.routes.hanseguide.ollama_is_reachable", fake_reachable
    )
    client = TestClient(app)
    response = client.get("/api/v1/hanseguide/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ollama"] is True
    assert body["project"] == "HanseGuide"


def test_hanseguide_health_degraded_without_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_reachable(**_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(
        "app.api.routes.hanseguide.ollama_is_reachable", fake_reachable
    )
    client = TestClient(app)
    response = client.get("/api/v1/hanseguide/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["ollama"] is False


@pytest.mark.asyncio
async def test_ollama_is_reachable_false_on_error_status() -> None:
    from app.hanseguide.ollama import ollama_is_reachable

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await ollama_is_reachable(client=client) is False
