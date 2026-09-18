"""Seed the `bids` table from JSON files under mock_data/ (each one
matches this app's "contract notice" schema — see
app.agents.bid_fit._extract_bid_notice_text, which is what turns a row's
raw_json back into text for the bid-fit pipeline).

Looks in mock_data/bids/*.json when that folder has files, otherwise any
*.json under mock_data/ (e.g. mock_data/contract_schema_mock_ted/).

Syncs the table to disk: new files are inserted, existing rows are
refreshed from the file, and rows whose source file is gone are
removed. Safe to call repeatedly — both from the CLI (`python
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


def mock_data_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "mock_data",  # repo root when this file is backend/app/
        Path("/app/mock_data"),  # Compose mount
        Path.cwd() / "mock_data",
        Path.cwd().parent / "mock_data",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def list_bid_json_files(root: Path | None = None) -> list[Path]:
    mock_data = root if root is not None else mock_data_root()
    if not mock_data.is_dir():
        return []
    bids_dir = mock_data / "bids"
    if bids_dir.is_dir():
        files = sorted(path for path in bids_dir.glob("*.json") if path.is_file())
        if files:
            return files
    return sorted(path for path in mock_data.rglob("*.json") if path.is_file())


def _extract_display_fields(data: dict) -> dict[str, str | None]:
    """Denormalized fields for showing a bid in a list without parsing
    raw_json — see Bid/BidBase in app.models."""
    procedure = data.get("procedure") or {}
    notice = data.get("notice") or {}
    places = data.get("placeOfPerformance") or []

    place_text = None
    if places:
        bits = [
            places[0].get(k)
            for k in ("city", "country", "nuts")
            if places[0].get(k)
        ]
        place_text = ", ".join(bits) or None

    return {
        "title": procedure.get("title"),
        "notice_identifier": notice.get("identifier"),
        "place_of_performance": place_text,
    }


def load_mock_bids(session: Session, mock_data_dir: Path | None = None) -> tuple[int, int]:
    """Make the `bids` table match the JSON files currently under
    mock_data/: insert new files, refresh existing rows from disk, and
    drop rows whose source file is gone. Returns (inserted, removed)."""
    files = list_bid_json_files(mock_data_dir)
    wanted = {path.name for path in files}
    existing = {bid.source_file: bid for bid in session.exec(select(Bid)).all()}

    inserted = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("Skipping %s: expected a JSON object", path)
            continue
        fields = _extract_display_fields(data)
        raw_json = json.dumps(data, ensure_ascii=False)
        bid = existing.get(path.name)
        if bid is None:
            session.add(
                Bid(source_file=path.name, raw_json=raw_json, **fields)
            )
            inserted += 1
        else:
            bid.raw_json = raw_json
            bid.title = fields["title"]
            bid.notice_identifier = fields["notice_identifier"]
            bid.place_of_performance = fields["place_of_performance"]

    removed = 0
    for source_file, bid in existing.items():
        if source_file not in wanted:
            session.delete(bid)
            removed += 1

    session.commit()
    return inserted, removed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    root = mock_data_root()
    with Session(engine) as session:
        inserted, removed = load_mock_bids(session, root)
    logger.info(
        "Loaded %s new bid(s), removed %s stale from %s",
        inserted,
        removed,
        root,
    )


if __name__ == "__main__":
    main()
