from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import Bid, BidPublic, Message
from app.seed_bids import list_bid_json_files, load_mock_bids, mock_data_root

router = APIRouter(prefix="/bids", tags=["bids"], dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[BidPublic])
def list_bids(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    List the seeded bids (shared pool, not owner-scoped — every user's
    dashboard analyzes the same bids against their own company profile).
    """
    return session.exec(select(Bid)).all()


@router.post("/load", response_model=Message)
def load_bids(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Populate the `bids` table from JSON files under mock_data/ (see
    app.seed_bids.load_mock_bids). Syncs to disk: new files are inserted,
    rows whose source file is gone are removed, so the table matches
    mock_data. Safe to call repeatedly from the dashboard's "Load data"
    button.
    """
    files = list_bid_json_files()
    if not files:
        raise HTTPException(
            status_code=404,
            detail=f"No bid JSON files found under {mock_data_root()}",
        )
    inserted, removed = load_mock_bids(session)
    total = session.exec(select(func.count()).select_from(Bid)).one()
    if inserted or removed:
        bits: list[str] = []
        if inserted:
            bits.append(f"loaded {inserted} new")
        if removed:
            bits.append(f"removed {removed} no longer in mock_data")
        return Message(message=f"{'; '.join(bits).capitalize()} ({total} total)")
    return Message(
        message=f"{total} bid{'s' if total != 1 else ''} already loaded from mock_data"
    )
