import time
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.services.edgar import EdgarClient

# SEC's own ticker->CIK directory, covering the full ~8000-company universe
# (not just companies we've ingested) — this is what backs company search.
_DIRECTORY_URL = "https://www.sec.gov/files/company_tickers.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60

_cache: list[dict[str, Any]] | None = None
_cache_fetched_at = 0.0


class CompanyDirectoryEntry(BaseModel):
    cik: str
    ticker: str
    name: str


def _load_directory() -> list[dict[str, Any]]:
    global _cache, _cache_fetched_at
    now = time.monotonic()
    if _cache is None or now - _cache_fetched_at > _CACHE_TTL_SECONDS:
        response = httpx.get(_DIRECTORY_URL, headers={"User-Agent": settings.SEC_EDGAR_USER_AGENT}, timeout=30.0)
        response.raise_for_status()
        _cache = list(response.json().values())
        _cache_fetched_at = now
    return _cache


def _match_score(query: str, ticker: str, name: str) -> int | None:
    if query == ticker:
        return 0
    if ticker.startswith(query):
        return 1
    if name.startswith(query):
        return 2
    if query in ticker or query in name:
        return 3
    return None


def search_companies(query: str, limit: int = 20) -> list[CompanyDirectoryEntry]:
    q = query.strip().lower()
    if not q:
        return []

    scored: list[tuple[int, CompanyDirectoryEntry]] = []
    for entry in _load_directory():
        ticker = str(entry["ticker"]).lower()
        name = str(entry["title"])
        score = _match_score(q, ticker, name.lower())
        if score is None:
            continue
        scored.append(
            (
                score,
                CompanyDirectoryEntry(cik=EdgarClient.normalize_cik(entry["cik_str"]), ticker=str(entry["ticker"]), name=name),
            )
        )

    scored.sort(key=lambda item: (item[0], item[1].name))
    return [entry for _, entry in scored[:limit]]
