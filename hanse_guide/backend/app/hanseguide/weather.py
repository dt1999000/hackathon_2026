import httpx

from app.hanseguide.client import DEFAULT_HEADERS, ExternalAPIError, http_client
from app.hanseguide.models import Weather

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes used by Open-Meteo.
_WEATHER_CODES: dict[int, str] = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with hail",
}


def weather_description(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _WEATHER_CODES.get(code, "Unknown")


async def get_weather(
    latitude: float,
    longitude: float,
    date: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> Weather:
    """Return weather for a location from Open-Meteo."""
    params: dict[str, str | float] = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "Europe/Berlin",
    }
    if date:
        params.update(
            {
                "start_date": date,
                "end_date": date,
                "daily": "temperature_2m_max,precipitation_probability_max,weather_code",
            }
        )
    else:
        params.update(
            {
                "current": "temperature_2m,precipitation,weather_code",
                "daily": "precipitation_probability_max",
                "forecast_days": 1,
            }
        )

    async with http_client(client) as http:
        try:
            response = await http.get(
                OPEN_METEO_URL,
                params=params,
                headers=DEFAULT_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise ExternalAPIError("open-meteo", str(exc)) from exc

    try:
        return _parse_weather(payload, dated=bool(date))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ExternalAPIError("open-meteo", "Unexpected weather payload") from exc


def _first_daily(daily: object, key: str) -> float | int | None:
    if not isinstance(daily, dict):
        return None
    values = daily.get(key)
    if not isinstance(values, list) or not values or values[0] is None:
        return None
    return values[0]


def _parse_weather(payload: object, *, dated: bool) -> Weather:
    if not isinstance(payload, dict):
        raise TypeError("weather payload must be an object")

    if dated:
        daily = payload.get("daily")
        temperature = _first_daily(daily, "temperature_2m_max")
        if temperature is None:
            raise KeyError("temperature_2m_max")
        precip = _first_daily(daily, "precipitation_probability_max")
        code_raw = _first_daily(daily, "weather_code")
        code = int(code_raw) if code_raw is not None else None
        return Weather(
            temperature=float(temperature),
            precipitation_probability=int(precip) if precip is not None else None,
            description=weather_description(code),
            weather_code=code,
        )

    current = payload.get("current")
    if not isinstance(current, dict) or current.get("temperature_2m") is None:
        raise KeyError("current.temperature_2m")
    temperature = float(current["temperature_2m"])
    code_raw = current.get("weather_code")
    code = int(code_raw) if code_raw is not None else None
    precip = _first_daily(payload.get("daily"), "precipitation_probability_max")
    return Weather(
        temperature=temperature,
        precipitation_probability=int(precip) if precip is not None else None,
        description=weather_description(code),
        weather_code=code,
    )
