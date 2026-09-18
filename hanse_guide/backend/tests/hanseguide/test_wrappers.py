from collections.abc import Callable
from urllib.parse import unquote

import httpx
import pytest

from app.hanseguide.client import ExternalAPIError, LocationNotFoundError
from app.hanseguide.geocode import geocode_location
from app.hanseguide.places import search_nearby_places
from app.hanseguide.route import calculate_route, haversine_distance_meters
from app.hanseguide.weather import get_weather, weather_description


def _client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_geocode_location_parses_nominatim() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["user_agent"] = request.headers["user-agent"]
        captured["viewbox"] = request.url.params["viewbox"]
        captured["countrycodes"] = request.url.params["countrycodes"]
        captured["bounded"] = request.url.params["bounded"]
        return httpx.Response(
            200,
            json=[
                {
                    "display_name": "Hamburg Hbf, Hamburg, Germany",
                    "lat": "53.5528",
                    "lon": "10.0066",
                }
            ],
        )

    async with _client_for(handler) as client:
        result = await geocode_location("Hamburg Hbf", client=client)

    assert result.latitude == pytest.approx(53.5528)
    assert result.longitude == pytest.approx(10.0066)
    assert "Hamburg Hbf" in result.display_name
    assert "HanseGuide" in captured["user_agent"]
    assert captured["countrycodes"] == "de"
    assert captured["bounded"] == "1"
    assert captured["viewbox"].startswith("9.70")


@pytest.mark.asyncio
async def test_geocode_location_not_found() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with _client_for(handler) as client:
        with pytest.raises(LocationNotFoundError):
            await geocode_location("Unknown Place", client=client)


@pytest.mark.asyncio
async def test_get_weather_current() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 18.4,
                    "weather_code": 2,
                },
                "daily": {"precipitation_probability_max": [20]},
            },
        )

    async with _client_for(handler) as client:
        weather = await get_weather(53.55, 10.00, client=client)

    assert weather.temperature == pytest.approx(18.4)
    assert weather.precipitation_probability == 20
    assert weather.description == "Partly cloudy"
    assert weather.weather_code == 2


@pytest.mark.asyncio
async def test_get_weather_for_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["start_date"] == "2026-09-13"
        assert request.url.params["end_date"] == "2026-09-13"
        return httpx.Response(
            200,
            json={
                "daily": {
                    "temperature_2m_max": [16.0],
                    "precipitation_probability_max": [80],
                    "weather_code": [61],
                }
            },
        )

    async with _client_for(handler) as client:
        weather = await get_weather(53.55, 10.00, date="2026-09-13", client=client)

    assert weather.temperature == pytest.approx(16.0)
    assert weather.precipitation_probability == 80
    assert weather.description == "Slight rain"


@pytest.mark.asyncio
async def test_search_nearby_places_parses_nodes_and_ways() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = unquote(request.content.decode())
        assert 'node["amenity"="library"]' in body
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 53.5498,
                        "lon": 10.0061,
                        "tags": {
                            "name": "Zentralbibliothek",
                            "addr:street": "Hühnerposten",
                            "addr:housenumber": "1",
                            "addr:city": "Hamburg",
                        },
                    },
                    {
                        "type": "way",
                        "id": 2,
                        "center": {"lat": 53.56, "lon": 10.02},
                        "tags": {"name": "Bücherhalle Hammerbrook"},
                    },
                    {
                        "type": "node",
                        "id": 3,
                        "lat": 53.55,
                        "lon": 10.01,
                        "tags": {},
                    },
                ]
            },
        )

    async with _client_for(handler) as client:
        places = await search_nearby_places(
            53.5528, 10.0066, "library", radius=1500, client=client
        )

    assert [place.name for place in places] == [
        "Zentralbibliothek",
        "Bücherhalle Hammerbrook",
    ]
    assert places[0].address == "Hühnerposten 1, Hamburg"
    assert places[0].place_type == "library"
    assert places[0].distance_meters is not None
    assert places[0].distance_meters < places[1].distance_meters


@pytest.mark.asyncio
async def test_search_nearby_places_retries_next_overpass_endpoint() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if "overpass-api.de" not in request.url.host:
            return httpx.Response(504, text="Gateway Timeout")
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "way",
                        "id": 10,
                        "center": {"lat": 53.561, "lon": 9.983},
                        "tags": {"name": "Planten un Blomen"},
                    }
                ]
            },
        )

    async with _client_for(handler) as client:
        places = await search_nearby_places(
            53.561, 9.983, "park", radius=1500, client=client
        )

    assert [place.name for place in places] == ["Planten un Blomen"]
    assert len(hosts) >= 2
    assert "overpass-api.de" in hosts[-1]


@pytest.mark.asyncio
async def test_search_nearby_places_raises_when_all_overpass_fail() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, text="Gateway Timeout")

    async with _client_for(handler) as client:
        with pytest.raises(ExternalAPIError, match="overpass"):
            await search_nearby_places(53.55, 10.0, "park", client=client)


@pytest.mark.asyncio
async def test_search_nearby_places_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        await search_nearby_places(53.55, 10.0, "museum")


def test_haversine_one_degree_longitude_at_equator() -> None:
    distance = haversine_distance_meters(0, 0, 0, 1)
    assert distance == pytest.approx(111_195, abs=50)


@pytest.mark.asyncio
async def test_calculate_route_uses_osrm() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "router.project-osrm.org" in request.url.host
        return httpx.Response(
            200,
            json={"routes": [{"distance": 450.4, "duration": 320.2}]},
        )

    async with _client_for(handler) as client:
        result = await calculate_route(53.55, 10.00, 53.551, 10.006, client=client)

    assert result.source == "osrm"
    assert result.distance_meters == 450
    assert result.duration_seconds == 320


@pytest.mark.asyncio
async def test_calculate_route_falls_back_to_haversine() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "busy"})

    async with _client_for(handler) as client:
        result = await calculate_route(0, 0, 0, 1, client=client)

    assert result.source == "haversine"
    assert result.distance_meters == pytest.approx(111_195, abs=50)
    assert result.duration_seconds is not None


@pytest.mark.asyncio
async def test_get_weather_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    async with _client_for(handler) as client:
        with pytest.raises(ExternalAPIError):
            await get_weather(53.55, 10.00, client=client)


def test_weather_description_unknown() -> None:
    assert weather_description(None) == "Unknown"
    assert weather_description(1234) == "Unknown"
