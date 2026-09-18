import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from app.hanseguide.client import ExternalAPIError
from app.hanseguide.models import Intent, IntentSource
from app.hanseguide.ollama import ollama_chat, parse_json_object

_BERLIN = ZoneInfo("Europe/Berlin")

_KNOWN_LOCATIONS: list[tuple[str, str]] = [
    ("planten um blomen", "Planten un Blomen"),
    ("planten un blomen", "Planten un Blomen"),
    ("hamburg hauptbahnhof", "Hamburg Hbf"),
    ("hamburg hbf", "Hamburg Hbf"),
    ("hauptbahnhof", "Hamburg Hbf"),
    ("jungfernstieg", "Jungfernstieg"),
    ("sternschanze", "Sternschanze"),
    ("hafencity", "HafenCity"),
    ("st. pauli", "St. Pauli"),
    ("st pauli", "St. Pauli"),
    ("eppendorf", "Eppendorf"),
    ("blankenese", "Blankenese"),
    ("hammerbrook", "Hammerbrook"),
    ("schanze", "Sternschanze"),
    ("altona", "Altona"),
    ("barmbek", "Barmbek"),
    ("hbf", "Hamburg Hbf"),
]

_LOCATION_RE = re.compile(
    r"(?:gần|near|around|at|in)\s+(.+?)(?:\s+(?:để|to|for|nếu|if)|[,.?!]|$)",
    re.IGNORECASE,
)

_INTENT_SYSTEM_PROMPT = """You extract a JSON intent for HanseGuide, a Hamburg local assistant.
Return ONLY a JSON object with this shape:
{
  "location": "Hamburg place name",
  "place_type": "cafe" | "library" | "park" | "mixed",
  "activity": "study" | "meet" | "walk" | "relax" | null,
  "date": "YYYY-MM-DD" or null,
  "time": "morning" | "afternoon" | "evening" | null,
  "radius": 1500,
  "preferences": ["quiet"],
  "include_park_if_dry": false
}
Rules:
- If the user named a location, copy that name exactly. Never substitute Hamburg Hbf or another district.
- Default location is "Hamburg Hbf" only if no location was mentioned.
- Do not invent or "correct" place names.
- study / homework / thư viện / học → place_type library, activity study.
- cafe / coffee / cà phê / meet a friend → cafe.
- park / walk / công viên / đi bộ → park.
- If the user wants a study place AND a park only if it is not raining, set place_type to library and include_park_if_dry to true.
- radius is meters, default 1500.
"""


def today_iso() -> str:
    return datetime.now(_BERLIN).date().isoformat()


def looks_vietnamese(text: str) -> bool:
    lowered = text.lower()
    if re.search(r"[ăâêôơưđáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ]", lowered):
        return True
    tokens = (
        "mình",
        "thư viện",
        "công viên",
        "cà phê",
        "gần",
        "chiều",
        "hôm nay",
        "yên tĩnh",
        "không mưa",
    )
    return any(token in lowered for token in tokens)


def parse_intent_keywords(message: str) -> Intent:
    """Rule-based intent used when Ollama is unavailable."""
    text = message.strip()
    lowered = text.lower()

    wants_library = bool(
        re.search(
            r"thư viện|library|libraries|\bhọc\b|study|studying|homework|đọc sách",
            lowered,
        )
    )
    wants_cafe = bool(
        re.search(r"café|cafe|cafes|cà phê|coffee|gặp bạn|meet a friend", lowered)
    )
    wants_park = bool(
        re.search(
            r"công viên|park|parks|đi bộ|walk|stroll|outdoor|picnic|relax outside",
            lowered,
        )
    )
    include_park_if_dry = bool(
        re.search(
            r"không mưa|no rain|not rain|doesn't rain|does not rain|if (?:it'?s )?dry",
            lowered,
        )
    )
    if wants_library and wants_park:
        include_park_if_dry = True

    if wants_library and wants_cafe and not wants_park:
        place_type: str = "mixed"
        activity = "study"
    elif wants_library:
        place_type = "library"
        activity = "study"
    elif wants_park and not wants_cafe:
        place_type = "park"
        activity = "walk"
    elif wants_cafe:
        place_type = "cafe"
        activity = "meet" if re.search(r"gặp|meet|friend", lowered) else None
    else:
        place_type = "cafe"
        activity = None

    preferences: list[str] = []
    if re.search(r"yên tĩnh|yen tinh|quiet|silent", lowered):
        preferences.append("quiet")

    time: str | None = None
    if re.search(r"chiều|afternoon|trưa", lowered):
        time = "afternoon"
    elif re.search(r"sáng|morning", lowered):
        time = "morning"
    elif re.search(r"tối|evening|tonight", lowered):
        time = "evening"

    date: str | None = None
    if re.search(r"hôm nay|today|chiều nay|sáng nay|tối nay", lowered):
        date = today_iso()

    return Intent(
        location=_extract_location(text, lowered),
        place_type=place_type,  # type: ignore[arg-type]
        activity=activity,
        date=date,
        time=time,
        radius=1500,
        preferences=preferences,
        include_park_if_dry=include_park_if_dry,
    )


def _extract_location(text: str, lowered: str) -> str:
    for needle, canonical in _KNOWN_LOCATIONS:
        if needle in lowered:
            return canonical
    match = _LOCATION_RE.search(text)
    if match:
        candidate = match.group(1).strip(" .,-")
        if candidate:
            return candidate
    return "Hamburg Hbf"


async def extract_intent_ollama(
    message: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> Intent:
    content = await ollama_chat(
        [
            {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        format_json=True,
        client=client,
    )
    data = parse_json_object(content)
    return Intent.model_validate(data)


async def extract_intent(
    message: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[Intent, IntentSource]:
    try:
        return await extract_intent_ollama(message, client=client), "ollama"
    except (ExternalAPIError, OSError, ValueError, ValidationError):
        return parse_intent_keywords(message), "keyword_fallback"
