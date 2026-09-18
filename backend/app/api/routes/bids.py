from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import Bid, BidPublic, Message
from app.seed_bids import load_mock_bids

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
    Populate the `bids` table from mock_data/bids/*.json (see
    app.seed_bids.load_mock_bids). Idempotent — already-loaded files
    (matched by filename) are skipped, so it's safe to call repeatedly,
    e.g. from the dashboard's "Load data" button.
    """
    inserted = load_mock_bids(session)
    return Message(message=f"Loaded {inserted} new bid(s)")
