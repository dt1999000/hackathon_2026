import time
from typing import Any, cast, get_args

import httpx

from app.hanseguide.client import (
    DEFAULT_HEADERS,
    OVERPASS_TIMEOUT,
    ExternalAPIError,
    http_client,
)
from app.hanseguide.models import Place, PlaceType
from app.hanseguide.route import haversine_distance_meters

# Public instances; overpass-api.de often returns 504 under load.
OVERPASS_ENDPOINTS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OVERPASS_URL = OVERPASS_ENDPOINTS[0]
_RETRY_STATUS = {429, 502, 503, 504}
_CACHE_TTL_SECONDS = 600.0
_place_cache: dict[tuple[float, float, str, int], tuple[float, list[Place]]] = {}

_PLACE_TAGS: dict[PlaceType, list[tuple[str, str]]] = {
    "cafe": [("amenity", "cafe")],
    "library": [("amenity", "library")],
    "park": [("leisure", "park")],
}


def _overpass_query(
    latitude: float,
    longitude: float,
    place_type: PlaceType,
    radius: int,
) -> str:
    filters: list[str] = []
    for key, value in _PLACE_TAGS[place_type]:
        around = f"(around:{radius},{latitude},{longitude})"
        filters.append(f'  node["{key}"="{value}"]{around};')
        filters.append(f'  way["{key}"="{value}"]{around};')
        if place_type == "park":
            filters.append(f'  relation["{key}"="{value}"]{around};')
    inner = "\n".join(filters)
    return (
        "[out:json][timeout:12][maxsize:16777216];\n"
        f"(\n{inner}\n);\nout center tags 25;"
    )


def _format_address(tags: dict[str, Any]) -> str | None:
    if tags.get("addr:full"):
        return str(tags["addr:full"])
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    line: list[str] = []
    if street and number:
        line.append(f"{street} {number}")
    elif street:
        line.append(str(street))
    postcode = tags.get("addr:postcode")
    city = tags.get("addr:city")
    if postcode and city:
        line.append(f"{postcode} {city}")
    elif city:
        line.append(str(city))
    return ", ".join(line) if line else None


def _element_coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _parse_place(
    element: dict[str, Any],
    *,
    place_type: PlaceType,
    origin_latitude: float,
    origin_longitude: float,
) -> Place | None:
    tags = element.get("tags") or {}
    name = tags.get("name")
    if not name:
        return None
    coords = _element_coordinates(element)
    if coords is None:
        return None
    latitude, longitude = coords
    distance = round(
        haversine_distance_meters(
            origin_latitude, origin_longitude, latitude, longitude
        )
    )
    osm_id = element.get("id")
    return Place(
        name=str(name),
        address=_format_address(tags),
        latitude=latitude,
        longitude=longitude,
        place_type=place_type,
        distance_meters=distance,
        osm_id=int(osm_id) if osm_id is not None else None,
    )


def _dedupe_places(
    elements: list[Any],
    *,
    place_type: PlaceType,
    origin_latitude: float,
    origin_longitude: float,
) -> list[Place]:
    places: list[Place] = []
    seen: set[tuple[str, float, float]] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        place = _parse_place(
            element,
            place_type=place_type,
            origin_latitude=origin_latitude,
            origin_longitude=origin_longitude,
        )
        if place is None:
            continue
        key = (place.name, round(place.latitude, 5), round(place.longitude, 5))
        if key in seen:
            continue
        seen.add(key)
        places.append(place)

    places.sort(key=lambda item: item.distance_meters or 0)
    return places


async def search_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str,
    radius: int = 1500,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[Place]:
    """Find cafés, libraries or parks around a location via Overpass."""
    if place_type not in get_args(PlaceType):
        raise ValueError(f"Unsupported place_type: {place_type!r}")
    typed = cast(PlaceType, place_type)
    cache_key = (round(latitude, 3), round(longitude, 3), typed, radius)
    use_cache = client is None
    if use_cache:
        cached = _place_cache.get(cache_key)
        if cached is not None:
            stored_at, places = cached
            if time.monotonic() - stored_at < _CACHE_TTL_SECONDS:
                return list(places)

    query = _overpass_query(latitude, longitude, typed, radius)
    payload: dict[str, Any] | None = None
    last_error: str | None = None

    async with http_client(client, timeout=OVERPASS_TIMEOUT) as http:
        for url in OVERPASS_ENDPOINTS:
            try:
                response = await http.post(
                    url,
                    data={"data": query},
                    headers=DEFAULT_HEADERS,
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                continue
            if response.status_code in _RETRY_STATUS:
                last_error = f"HTTP {response.status_code} from {url}"
                continue
            try:
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = str(exc)
                continue
            if not isinstance(data, dict):
                last_error = "Unexpected places payload"
                continue
            payload = data
            break

    if payload is None:
        raise ExternalAPIError(
            "overpass",
            last_error or "All Overpass endpoints failed",
        )

    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ExternalAPIError("overpass", "Unexpected places payload")

    places = _dedupe_places(
        elements,
        place_type=typed,
        origin_latitude=latitude,
        origin_longitude=longitude,
    )
    if use_cache:
        _place_cache[cache_key] = (time.monotonic(), list(places))
    return places
