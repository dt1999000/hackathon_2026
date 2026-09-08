import time
from typing import Any

import httpx

from app.core.config import settings

# SEC's fair-access guidance asks automated tools to stay under ~10
# requests/second (https://www.sec.gov/os/webmaster-faq#developers).
_MIN_REQUEST_INTERVAL_SECONDS = 0.11


class EdgarClient:
    """Client for the SEC EDGAR data APIs (data.sec.gov)."""

    def __init__(self, user_agent: str | None = None) -> None:
        self.user_agent = user_agent or settings.SEC_EDGAR_USER_AGENT
        self._last_request_at: float = 0.0

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        """Zero-pad a CIK to the 10-digit format SEC's API URLs expect."""
        return str(int(cik)).zfill(10)

    def _get(self, url: str) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        response = httpx.get(url, headers={"User-Agent": self.user_agent}, timeout=30.0)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return dict(response.json())

    def get_submissions(self, cik: str | int) -> dict[str, Any]:
        """Company profile plus its recent filing history."""
        padded = self.normalize_cik(cik)
        return self._get(f"https://data.sec.gov/submissions/CIK{padded}.json")

    def get_company_facts(self, cik: str | int) -> dict[str, Any]:
        """All XBRL structured facts SEC has tagged for this company, by concept."""
        padded = self.normalize_cik(cik)
        return self._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json")
