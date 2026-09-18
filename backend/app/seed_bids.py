"""Seed the `bids` table from the JSON files in mock_data/bids/ (each one
matches this app's "contract notice" schema — see
app.agents.bid_fit._extract_bid_notice_text, which is what turns a row's
raw_json back into text for the bid-fit pipeline).

Idempotent: skips any file whose name is already present as a bid's
source_file, so it's safe to call repeatedly — both from the CLI (`python
app/seed_bids.py`) and from the dashboard's "Load data" button
(POST /bids/load, see app.api.routes.bids), which calls load_mock_bids
directly rather than shelling out to this script.
"""

import json
import logging
from pathlib import Path

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Bid

logger = logging.getLogger(__name__)

MOCK_BIDS_DIR = Path(__file__).resolve().parents[2] / "mock_data" / "bids"


def _extract_display_fields(data: dict) -> dict[str, str | None]:
    """Denormalized fields for showing a bid in a list without parsing
    raw_json — see Bid/BidBase in app.models."""
    procedure = data.get("procedure") or {}
    notice = data.get("notice") or {}
    places = data.get("placeOfPerformance") or []

    place_text = None
    if places:
        bits = [places[0].get(k) for k in ("city", "country") if places[0].get(k)]
        place_text = ", ".join(bits) or None

    return {
        "title": procedure.get("title"),
        "notice_identifier": notice.get("identifier"),
        "place_of_performance": place_text,
    }


def load_mock_bids(session: Session) -> int:
    """Insert every mock_data/bids/*.json file not already in the `bids`
    table (matched by filename). Returns how many new rows were added."""
    existing = set(session.exec(select(Bid.source_file)).all())
    inserted = 0
    for path in sorted(MOCK_BIDS_DIR.glob("*.json")):
        if path.name in existing:
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        bid = Bid(
            source_file=path.name,
            raw_json=json.dumps(data, ensure_ascii=False),
            **_extract_display_fields(data),
        )
        session.add(bid)
        inserted += 1
    session.commit()
    return inserted


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with Session(engine) as session:
        count = load_mock_bids(session)
    logger.info(f"Loaded {count} new bid(s) from {MOCK_BIDS_DIR}")


if __name__ == "__main__":
    main()
