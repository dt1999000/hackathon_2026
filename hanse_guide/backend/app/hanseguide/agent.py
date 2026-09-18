import asyncio
import json
from typing import cast, get_args

import httpx

from app.hanseguide.client import ExternalAPIError
from app.hanseguide.geocode import geocode_location
from app.hanseguide.intent import extract_intent, looks_vietnamese
from app.hanseguide.models import (
    ChatResponse,
    Intent,
    Place,
    PlaceRecommendation,
    PlaceType,
    Weather,
)
from app.hanseguide.ollama import ollama_chat
from app.hanseguide.places import search_nearby_places
from app.hanseguide.weather import get_weather

RAIN_PROBABILITY_THRESHOLD = 50
MAX_PLACES = 5

_ANSWER_SYSTEM_PROMPT = """You are HanseGuide, a local assistant for Hamburg.
Write a short, friendly recommendation (2-4 sentences).
Match the user's language (Vietnamese or English).
You MUST only mention place names from the provided JSON list.
Do not invent cafés, libraries, parks, addresses, or distances.
If the list is empty, say you could not find matching OpenStreetMap places.
Mention the weather briefly when it is provided.
"""


def is_rainy(weather: Weather | None) -> bool:
    if weather is None or weather.precipitation_probability is None:
        return False
    return weather.precipitation_probability >= RAIN_PROBABILITY_THRESHOLD


def place_search_types(intent: Intent, weather: Weather | None) -> list[PlaceType]:
    types: list[PlaceType] = []
    if intent.place_type == "mixed":
        types.extend(["cafe", "library"])
    elif intent.place_type in get_args(PlaceType):
        types.append(cast(PlaceType, intent.place_type))
    else:
        types.append("cafe")

    if intent.include_park_if_dry and not is_rainy(weather) and "park" not in types:
        types.append("park")
    return types


def _place_score(place: Place, intent: Intent) -> tuple[int, int]:
    distance = place.distance_meters if place.distance_meters is not None else 10_000
    bonus = 0
    if intent.activity == "study" and place.place_type == "library":
        bonus += 5000
    if "quiet" in intent.preferences and place.place_type == "library":
        bonus += 2000
    if intent.place_type == place.place_type:
        bonus += 1000
    if intent.activity == "walk" and place.place_type == "park":
        bonus += 4000
    if intent.activity in {"meet", None} and place.place_type == "cafe":
        bonus += 500
    return (-bonus, distance)


def _reason_for(place: Place, intent: Intent, weather: Weather | None, vietnamese: bool) -> str:
    distance = (
        f"{place.distance_meters}m"
        if place.distance_meters is not None
        else None
    )
    if vietnamese:
        if place.place_type == "library":
            base = "Thư viện phù hợp để học, yên tĩnh hơn quán cà phê."
        elif place.place_type == "park":
            base = "Công viên gần đó, hợp để đi bộ khi trời không mưa."
        else:
            base = "Quán cà phê gần vị trí bạn chọn, phù hợp gặp bạn hoặc làm việc."
        if distance:
            return f"{base} Cách khoảng {distance}."
        return base

    if place.place_type == "library":
        base = "A library that works well for studying."
    elif place.place_type == "park":
        if is_rainy(weather):
            base = "A park nearby; bring rain protection."
        else:
            base = "A nearby park for a walk while rain risk is low."
    else:
        base = "A café close to your location for work or meeting friends."
    if intent.activity == "study" and place.place_type == "library":
        base = "Quiet indoor place suitable for studying."
    if distance:
        return f"{base} About {distance} away."
    return base


def rank_places(
    places: list[Place],
    intent: Intent,
    weather: Weather | None,
    *,
    vietnamese: bool,
    limit: int = MAX_PLACES,
) -> list[PlaceRecommendation]:
    unique: list[Place] = []
    seen: set[tuple[str, float, float]] = set()
    for place in places:
        key = (place.name, round(place.latitude, 5), round(place.longitude, 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(place)

    unique.sort(key=lambda item: _place_score(item, intent))
    if intent.include_park_if_dry and is_rainy(weather) and intent.place_type != "park":
        unique = [item for item in unique if item.place_type != "park"]

    selected: list[Place] = []
    if intent.include_park_if_dry and not is_rainy(weather):
        primary = [item for item in unique if item.place_type != "park"]
        parks = [item for item in unique if item.place_type == "park"]
        selected.extend(primary[: max(limit - 1, 1)])
        if parks:
            selected.extend(parks[: max(limit - len(selected), 1)])
        selected = selected[:limit]
    else:
        selected = unique[:limit]

    return [
        PlaceRecommendation(
            name=place.name,
            address=place.address,
            distance_meters=place.distance_meters,
            latitude=place.latitude,
            longitude=place.longitude,
            reason=_reason_for(place, intent, weather, vietnamese),
            place_type=place.place_type,
        )
        for place in selected
    ]


def template_answer(
    message: str,
    intent: Intent,
    weather: Weather | None,
    places: list[PlaceRecommendation],
) -> str:
    vietnamese = looks_vietnamese(message)
    weather_bit = ""
    if weather is not None:
        rain = (
            f"{weather.precipitation_probability}%"
            if weather.precipitation_probability is not None
            else "unknown"
        )
        if vietnamese:
            weather_bit = (
                f"Thời tiết quanh {intent.location}: {weather.description}, "
                f"{weather.temperature:.0f}°C, xác suất mưa {rain}. "
            )
        else:
            weather_bit = (
                f"Weather near {intent.location}: {weather.description}, "
                f"{weather.temperature:.0f}°C, rain chance {rain}. "
            )

    if not places:
        if vietnamese:
            skipped_park = ""
            if intent.include_park_if_dry and is_rainy(weather):
                skipped_park = " Trời có vẻ mưa nên mình chưa gợi ý công viên."
            return (
                weather_bit
                + "Hiện chưa tìm thấy địa điểm phù hợp trên OpenStreetMap."
                + skipped_park
            )
        skipped_park = ""
        if intent.include_park_if_dry and is_rainy(weather):
            skipped_park = " Parks were skipped because rain is likely."
        return (
            weather_bit
            + "I could not find matching places from OpenStreetMap."
            + skipped_park
        )

    top = places[0]
    names = ", ".join(place.name for place in places)
    if vietnamese:
        extra = ""
        if intent.include_park_if_dry and is_rainy(weather):
            extra = " Vì khả năng mưa cao, mình chưa gợi ý công viên."
        elif any(place.place_type == "park" for place in places):
            extra = " Trời khá ổn nên mình thêm công viên gần đó."
        return (
            f"{weather_bit}{top.name} là lựa chọn phù hợp nhất"
            f"{f' ({top.address})' if top.address else ''}. "
            f"Các gợi ý từ dữ liệu bản đồ: {names}.{extra}"
        )

    extra = ""
    if intent.include_park_if_dry and is_rainy(weather):
        extra = " Parks were skipped because rain is likely."
    elif any(place.place_type == "park" for place in places):
        extra = " It looks dry enough to add a nearby park."
    address = f" ({top.address})" if top.address else ""
    return (
        f"{weather_bit}{top.name}{address} is the strongest match. "
        f"Map data suggestions: {names}.{extra}"
    )


async def generate_answer(
    message: str,
    intent: Intent,
    weather: Weather | None,
    places: list[PlaceRecommendation],
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    fallback = template_answer(message, intent, weather, places)
    allowed = [place.name for place in places]
    payload = {
        "user_message": message,
        "intent": intent.model_dump(),
        "weather": weather.model_dump() if weather else None,
        "places": [place.model_dump() for place in places],
        "allowed_place_names": allowed,
    }
    try:
        content = await ollama_chat(
            [
                {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            client=client,
        )
    except (ExternalAPIError, OSError, ValueError):
        return fallback
    stripped = content.strip()
    if not stripped:
        return fallback
    if allowed and not any(name in stripped for name in allowed):
        return fallback
    return stripped


async def run_agent(
    message: str,
    *,
    client: httpx.AsyncClient | None = None,
    ollama_client: httpx.AsyncClient | None = None,
) -> ChatResponse:
    """Select tools, collect API data and generate the final answer."""
    tools_used: list[str] = []
    intent, _source = await extract_intent(message, client=ollama_client)

    origin = await geocode_location(intent.location, client=client)
    tools_used.append("geocode_location")

    weather: Weather | None = None
    try:
        weather = await get_weather(
            origin.latitude,
            origin.longitude,
            date=intent.date,
            client=client,
        )
        tools_used.append("get_weather")
    except ExternalAPIError:
        weather = None

    types = place_search_types(intent, weather)
    search_results = await asyncio.gather(
        *[
            search_nearby_places(
                origin.latitude,
                origin.longitude,
                place_type,
                radius=intent.radius,
                client=client,
            )
            for place_type in types
        ],
        return_exceptions=True,
    )
    merged: list[Place] = []
    for result in search_results:
        if isinstance(result, ExternalAPIError):
            continue
        if isinstance(result, BaseException):
            raise result
        merged.extend(result)
    if types:
        tools_used.append("search_nearby_places")

    vietnamese = looks_vietnamese(message)
    places = rank_places(merged, intent, weather, vietnamese=vietnamese)
    answer = await generate_answer(
        message,
        intent,
        weather,
        places,
        client=ollama_client,
    )
    return ChatResponse(
        answer=answer,
        intent=intent,
        weather=weather,
        places=places,
        tools_used=tools_used,
    )
