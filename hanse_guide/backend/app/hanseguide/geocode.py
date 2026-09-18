import httpx

from app.hanseguide.client import (
    DEFAULT_HEADERS,
    ExternalAPIError,
    LocationNotFoundError,
    http_client,
)
from app.hanseguide.models import GeocodeResult

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# left, bottom, right, top — Hamburg approx.
HAMBURG_VIEWBOX = "9.70,53.38,10.35,53.75"


async def geocode_location(
    location: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> GeocodeResult:
    """Convert a place name or address into coordinates via Nominatim."""
    query = location.strip()
    if not query:
        raise LocationNotFoundError(location)

    params = {
        "q": query,
        "format": "json",
        "limit": "1",
        "countrycodes": "de",
        "viewbox": HAMBURG_VIEWBOX,
        "bounded": "1",
        "addressdetails": "0",
    }
    async with http_client(client) as http:
        try:
            response = await http.get(
                NOMINATIM_URL,
                params=params,
                headers=DEFAULT_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise ExternalAPIError("nominatim", str(exc)) from exc

    if not isinstance(payload, list) or not payload:
        raise LocationNotFoundError(query)

    hit = payload[0]
    try:
        return GeocodeResult(
            display_name=str(hit.get("display_name") or query),
            latitude=float(hit["lat"]),
            longitude=float(hit["lon"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalAPIError("nominatim", "Unexpected geocoding payload") from exc
