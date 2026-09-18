import httpx
import pytest
from fastapi.testclient import TestClient

from app.hanseguide.agent import generate_answer, rank_places, run_agent
from app.hanseguide.client import ExternalAPIError, LocationNotFoundError
from app.hanseguide.intent import extract_intent
from app.hanseguide.models import (
    ChatResponse,
    GeocodeResult,
    Intent,
    Place,
    PlaceRecommendation,
    Weather,
)
from app.main import app


def _library() -> Place:
    return Place(
        name="Zentralbibliothek",
        address="Hühnerposten 1, Hamburg",
        latitude=53.5498,
        longitude=10.0061,
        place_type="library",
        distance_meters=450,
        osm_id=1,
    )


def _park() -> Place:
    return Place(
        name="Lohsepark",
        address="HafenCity, Hamburg",
        latitude=53.541,
        longitude=10.002,
        place_type="park",
        distance_meters=900,
        osm_id=2,
    )


def test_rank_places_keeps_park_when_dry() -> None:
    intent = Intent(
        location="Hamburg Hbf",
        place_type="library",
        activity="study",
        preferences=["quiet"],
        include_park_if_dry=True,
    )
    weather = Weather(
        temperature=18,
        precipitation_probability=20,
        description="Partly cloudy",
    )
    ranked = rank_places(
        [_park(), _library()],
        intent,
        weather,
        vietnamese=True,
    )
    names = [place.name for place in ranked]
    assert names[0] == "Zentralbibliothek"
    assert "Lohsepark" in names
    assert all(place.reason for place in ranked)


def test_rank_places_skips_park_when_rainy() -> None:
    intent = Intent(
        location="Hamburg Hbf",
        place_type="library",
        include_park_if_dry=True,
    )
    weather = Weather(
        temperature=12,
        precipitation_probability=80,
        description="Rain",
    )
    ranked = rank_places(
        [_library(), _park()],
        intent,
        weather,
        vietnamese=False,
    )
    assert [place.name for place in ranked] == ["Zentralbibliothek"]


@pytest.mark.asyncio
async def test_extract_intent_uses_ollama_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": (
                        '{"location":"Altona","place_type":"cafe",'
                        '"activity":"meet","radius":1500,'
                        '"preferences":[],"include_park_if_dry":false}'
                    )
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        intent, source = await extract_intent("coffee in Altona", client=client)

    assert source == "ollama"
    assert intent.location == "Altona"
    assert intent.place_type == "cafe"


@pytest.mark.asyncio
async def test_extract_intent_falls_back_when_ollama_down() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        intent, source = await extract_intent(
            "Find a library near Hamburg Hbf to study",
            client=client,
        )

    assert source == "keyword_fallback"
    assert intent.place_type == "library"
    assert intent.location == "Hamburg Hbf"


@pytest.mark.asyncio
async def test_run_agent_uses_api_places_only(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_extract(_message: str, **_kwargs: object):
        return (
            Intent(
                location="Hamburg Hbf",
                place_type="library",
                activity="study",
                include_park_if_dry=True,
            ),
            "keyword_fallback",
        )

    async def fake_geocode(_location: str, **_kwargs: object):
        return GeocodeResult(
            display_name="Hamburg Hbf",
            latitude=53.5528,
            longitude=10.0066,
        )

    async def fake_weather(*_args: object, **_kwargs: object) -> Weather:
        return Weather(
            temperature=18,
            precipitation_probability=10,
            description="Clear",
        )

    async def fake_places(
        _lat: float,
        _lon: float,
        place_type: str,
        *_args: object,
        **_kwargs: object,
    ) -> list[Place]:
        if place_type == "library":
            return [_library()]
        if place_type == "park":
            return [_park()]
        return []

    async def fake_answer(*_args: object, **_kwargs: object) -> str:
        return "Zentralbibliothek là lựa chọn phù hợp nhất."

    monkeypatch.setattr("app.hanseguide.agent.extract_intent", fake_extract)
    monkeypatch.setattr("app.hanseguide.agent.geocode_location", fake_geocode)
    monkeypatch.setattr("app.hanseguide.agent.get_weather", fake_weather)
    monkeypatch.setattr("app.hanseguide.agent.search_nearby_places", fake_places)
    monkeypatch.setattr("app.hanseguide.agent.generate_answer", fake_answer)

    result = await run_agent("Học gần Hamburg Hbf")
    names = {place.name for place in result.places}
    assert names == {"Zentralbibliothek", "Lohsepark"}
    assert "Invented Café" not in names
    assert result.tools_used == [
        "geocode_location",
        "get_weather",
        "search_nearby_places",
    ]
    assert "Zentralbibliothek" in result.answer


@pytest.mark.asyncio
async def test_run_agent_continues_when_overpass_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_extract(_message: str, **_kwargs: object):
        return (
            Intent(location="Planten un Blomen", place_type="park", activity="walk"),
            "keyword_fallback",
        )

    async def fake_geocode(_location: str, **_kwargs: object):
        return GeocodeResult(
            display_name="Planten un Blomen",
            latitude=53.561,
            longitude=9.983,
        )

    async def fake_weather(*_args: object, **_kwargs: object) -> Weather:
        return Weather(
            temperature=16,
            precipitation_probability=10,
            description="Clear",
        )

    async def fake_places(*_args: object, **_kwargs: object) -> list[Place]:
        raise ExternalAPIError("overpass", "HTTP 504")

    monkeypatch.setattr("app.hanseguide.agent.extract_intent", fake_extract)
    monkeypatch.setattr("app.hanseguide.agent.geocode_location", fake_geocode)
    monkeypatch.setattr("app.hanseguide.agent.get_weather", fake_weather)
    monkeypatch.setattr("app.hanseguide.agent.search_nearby_places", fake_places)

    result = await run_agent("Plan a walk - park near Planten um Blomen.")
    assert result.places == []
    assert result.weather is not None
    assert "OpenStreetMap" in result.answer
    assert result.tools_used == [
        "geocode_location",
        "get_weather",
        "search_nearby_places",
    ]


@pytest.mark.asyncio
async def test_generate_answer_falls_back_if_model_invents_places() -> None:
    places = [
        PlaceRecommendation(
            name="Zentralbibliothek",
            address="Hühnerposten 1, Hamburg",
            distance_meters=450,
            latitude=53.5498,
            longitude=10.0061,
            reason="Quiet",
            place_type="library",
        )
    ]
    intent = Intent(location="Hamburg Hbf", place_type="library")
    weather = Weather(temperature=18, precipitation_probability=10, description="Clear")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"content": "You should go to Made Up Coffee Shop."}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        answer = await generate_answer(
            "Find a library",
            intent,
            weather,
            places,
            client=client,
        )

    assert "Zentralbibliothek" in answer
    assert "Made Up Coffee Shop" not in answer


def test_chat_endpoint_returns_agent_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_agent(message: str) -> ChatResponse:
        return ChatResponse(
            answer=f"Heard: {message}",
            intent=Intent(location="Hamburg Hbf", place_type="library"),
            weather=Weather(
                temperature=18,
                precipitation_probability=20,
                description="Cloudy",
            ),
            places=[
                PlaceRecommendation(
                    name="Zentralbibliothek",
                    address="Hühnerposten 1, Hamburg",
                    distance_meters=450,
                    latitude=53.5498,
                    longitude=10.0061,
                    reason="Near the station and good for studying.",
                    place_type="library",
                )
            ],
            tools_used=["geocode_location", "get_weather", "search_nearby_places"],
        )

    monkeypatch.setattr("app.api.routes.hanseguide.run_agent", fake_run_agent)
    client = TestClient(app)
    response = client.post(
        "/api/v1/hanseguide/chat",
        json={"message": "Tìm một thư viện gần Hamburg Hbf để học chiều nay."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["places"][0]["name"] == "Zentralbibliothek"
    assert body["tools_used"] == [
        "geocode_location",
        "get_weather",
        "search_nearby_places",
    ]


def test_chat_endpoint_maps_location_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_agent(_message: str) -> ChatResponse:
        raise LocationNotFoundError("Atlantis")

    monkeypatch.setattr("app.api.routes.hanseguide.run_agent", fake_run_agent)
    client = TestClient(app)
    response = client.post(
        "/api/v1/hanseguide/chat",
        json={"message": "near Atlantis"},
    )
    assert response.status_code == 404


def test_chat_endpoint_maps_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_agent(_message: str) -> ChatResponse:
        raise ExternalAPIError("overpass", "timeout")

    monkeypatch.setattr("app.api.routes.hanseguide.run_agent", fake_run_agent)
    client = TestClient(app)
    response = client.post(
        "/api/v1/hanseguide/chat",
        json={"message": "find a cafe"},
    )
    assert response.status_code == 502
