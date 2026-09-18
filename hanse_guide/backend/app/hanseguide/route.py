import math

import httpx

from app.hanseguide.client import DEFAULT_HEADERS, http_client
from app.hanseguide.models import RouteResult

OSRM_URL = "https://router.project-osrm.org/route/v1/foot"
EARTH_RADIUS_METERS = 6_371_000
WALKING_SPEED_MPS = 1.4


def haversine_distance_meters(
    start_latitude: float,
    start_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> float:
    """Great-circle distance in meters."""
    phi1 = math.radians(start_latitude)
    phi2 = math.radians(destination_latitude)
    delta_phi = math.radians(destination_latitude - start_latitude)
    delta_lambda = math.radians(destination_longitude - start_longitude)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return EARTH_RADIUS_METERS * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _haversine_route(
    start_latitude: float,
    start_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> RouteResult:
    distance = haversine_distance_meters(
        start_latitude,
        start_longitude,
        destination_latitude,
        destination_longitude,
    )
    duration = round(distance / WALKING_SPEED_MPS)
    return RouteResult(
        distance_meters=round(distance),
        duration_seconds=duration,
        source="haversine",
    )


async def calculate_route(
    start_latitude: float,
    start_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
    *,
    client: httpx.AsyncClient | None = None,
    use_osrm: bool = True,
) -> RouteResult:
    """Calculate walking distance and duration. Falls back to haversine."""
    fallback = _haversine_route(
        start_latitude,
        start_longitude,
        destination_latitude,
        destination_longitude,
    )
    if not use_osrm:
        return fallback

    path = (
        f"{OSRM_URL}/{start_longitude},{start_latitude};"
        f"{destination_longitude},{destination_latitude}"
    )
    async with http_client(client) as http:
        try:
            response = await http.get(
                path,
                params={"overview": "false"},
                headers=DEFAULT_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
            routes = payload.get("routes") if isinstance(payload, dict) else None
            if not routes:
                return fallback
            route = routes[0]
            return RouteResult(
                distance_meters=round(float(route["distance"])),
                duration_seconds=round(float(route["duration"])),
                source="osrm",
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            return fallback
