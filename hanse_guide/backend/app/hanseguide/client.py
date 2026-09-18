from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

USER_AGENT = "HanseGuide/1.0 (Hamburg hackathon; https://openstreetmap.org)"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
OVERPASS_TIMEOUT = httpx.Timeout(12.0, connect=5.0)


class ExternalAPIError(Exception):
    def __init__(self, service: str, message: str) -> None:
        self.service = service
        super().__init__(f"{service}: {message}")


class LocationNotFoundError(ExternalAPIError):
    def __init__(self, location: str) -> None:
        super().__init__("nominatim", f"No coordinates found for {location!r}")
        self.location = location


@asynccontextmanager
async def http_client(
    client: httpx.AsyncClient | None = None,
    *,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
    ) as owned:
        yield owned
