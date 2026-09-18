"""Dashboard "bids" API: read-only view over the Contract table (populated
by the existing crawl/import pipelines -- see run_contract_pipelines.py),
plus pin/unpin state and a Refresh action that re-runs those pipelines in
the background and reports how many bids are new.

This file is new code, written to *display* what the existing pipelines
already produce. It does not modify ted_pipeline.py,
CPV45_Eforms_Attachments_Pipeline.py, build_schema_from_agent_input.py,
dedupe_contracts.py, run_contract_pipelines.py or scripts/import_contracts.py
-- it only shells out to run_contract_pipelines.py exactly the way its own
module docstring documents (`run_contract_pipelines.py --import-db`).
"""

import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.api.deps import SessionDep, get_current_user
from app.core.db import engine
from app.models import (
    BidPin,
    Contract,
    DashboardRefreshState,
    Message,
    get_datetime_utc,
)

router = APIRouter(prefix="/bids", tags=["bids"], dependencies=[Depends(get_current_user)])

# routes/ -> api/ -> app/ -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[3]
RUN_PIPELINES_SCRIPT = BACKEND_DIR / "app" / "run_contract_pipelines.py"

# A full run (TED search + PDF downloads + oeffentlichevergabe.de CSV/eForms
# export + dedupe + DB import) can legitimately take several minutes.
REFRESH_TIMEOUT_SECONDS = int(os.getenv("BIDS_REFRESH_TIMEOUT_SECONDS", str(30 * 60)))
# If a "running" refresh has been going for way longer than its own timeout
# could ever take, something crashed without updating the row (e.g. the API
# process was restarted mid-refresh) -- let the next click start a new one
# instead of leaving the dashboard stuck on "Refreshing..." forever.
STALE_RUNNING_AFTER_SECONDS = REFRESH_TIMEOUT_SECONDS + 120

SOURCE_FILTER_MAP = {"ted": "TED", "oeffentlichevergabe": "oeffentlichevergabe.de"}


# --- response schemas (API-facing only; DB tables live in app.models) -----


class BidPublic(BaseModel):
    id: uuid.UUID
    source_system: str
    buyer: str | None
    link: str | None
    estimated_value: float | None
    currency: str | None
    deadline_date: str | None
    deadline_time: str | None
    procedure_title: str | None
    publication_date: str | None
    pinned: bool
    is_new: bool


class BidsPublic(BaseModel):
    data: list[BidPublic]
    count: int


class RefreshStatusPublic(BaseModel):
    status: Literal["idle", "running", "error"]
    last_refreshed_at: datetime | None
    new_count: int
    message: str
    error: str | None


# --- helpers ----------------------------------------------------------------


def build_source_link(source_system: str, notice_identifier: str | None) -> str | None:
    """Notice-level link (same for every lot of the same notice, so it
    isn't split by LOT the way the raw per-lot documents are)."""
    if not notice_identifier:
        return None
    if source_system == "TED":
        # Confirmed against TED's own sitemap and a live notice fetch:
        # the notice detail page is at /notice/-/detail/<id>, not
        # /notice/<id> (which 404s -- that was the bug). The PDF documents
        # ted_pipeline.py downloads use a *different* path
        # (/notice/<id>/pdf, see its own document links), which is not a
        # human-viewable notice page and isn't what "View bid" should open.
        return f"https://ted.europa.eu/en/notice/-/detail/{notice_identifier}"
    if source_system == "oeffentlichevergabe.de":
        return (
            "https://oeffentlichevergabe.de/ui/en/search/details"
            f"?noticeId={notice_identifier}"
        )
    return None


def contract_to_public(
    contract: Contract, *, pinned: bool, new_since_at: datetime | None
) -> BidPublic:
    return BidPublic(
        id=contract.id,
        source_system=contract.source_system,
        buyer=", ".join(contract.buyer_names) if contract.buyer_names else None,
        link=build_source_link(contract.source_system, contract.notice_identifier),
        estimated_value=contract.estimated_value,
        currency=contract.currency,
        deadline_date=contract.deadline_date,
        deadline_time=contract.deadline_time,
        procedure_title=contract.procedure_title,
        publication_date=contract.publication_date,
        pinned=pinned,
        is_new=new_since_at is not None and contract.created_at > new_since_at,
    )


def get_or_create_state(session: Session) -> DashboardRefreshState:
    state = session.get(DashboardRefreshState, 1)
    if not state:
        state = DashboardRefreshState(id=1)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def live_new_count(session: Session, state: DashboardRefreshState) -> int:
    """How many bids are flagged "New!" right now -- the exact same
    cutoff (state.new_since_at) that contract_to_public()'s is_new uses for
    each row, computed live instead of trusted from a stored snapshot.

    state.last_new_count is only ever written at the moment a Refresh run
    finishes, so it goes stale the instant the DB changes some other way --
    e.g. running run_contract_pipelines.py by hand (as documented in its own
    module docstring) instead of clicking Refresh in the dashboard. That
    mismatch is exactly what made the header say "0 new bids" while
    individual rows still showed "New!" badges: the badges call is_new
    live off new_since_at on every load, but the header trusted the old
    snapshot. Computing both off the same live query keeps them consistent
    no matter how the Contract table was populated.
    """
    if state.new_since_at is None:
        return 0
    count_statement = (
        select(func.count())
        .select_from(Contract)
        .where(col(Contract.created_at) > state.new_since_at)
    )
    return session.exec(count_statement).one()


def status_message(new_count: int, state: DashboardRefreshState) -> str:
    if state.status == "running":
        return "Refreshing…"
    if state.status == "error":
        return state.last_error or "Refresh failed."
    if state.last_refreshed_at is not None or state.new_since_at is not None:
        return (
            f"Found {new_count} new bid{'s' if new_count != 1 else ''}."
            if new_count
            else "No new bids found."
        )
    return "Not refreshed yet."


def to_status_public(
    session: Session, state: DashboardRefreshState, *, message: str | None = None
) -> RefreshStatusPublic:
    new_count = live_new_count(session, state)
    return RefreshStatusPublic(
        status=state.status,  # type: ignore[arg-type]
        last_refreshed_at=state.last_refreshed_at,
        new_count=new_count,
        message=message if message is not None else status_message(new_count, state),
        error=state.last_error,
    )


def _run_refresh(started_at: datetime, previous_new_since_at: datetime | None) -> None:
    """Runs in a background thread (FastAPI BackgroundTasks) after the
    response for POST /bids/refresh has already gone out."""
    with Session(engine) as session:
        state = session.get(DashboardRefreshState, 1)
        if state is None:
            state = DashboardRefreshState(id=1)

        env = os.environ.copy()
        # Adaptive target day: whatever calendar day Refresh was clicked on,
        # not whichever fixed value PIPELINE_TARGET_DATE happens to already
        # be set to in the shell/.env, and not the pipelines' own "yesterday"
        # fallback (see ted_pipeline.py / run_contract_pipelines.py --
        # unset, both default to yesterday because TED's API doesn't publish
        # the current day's notices immediately). run_contract_pipelines.py
        # reads this same env var and cascades it to both sub-pipelines, so
        # setting it here -- not editing those files -- is enough.
        # Caveat: TED specifically may still come back with 0 results for
        # *today* if it hasn't published yet; oeffentlichevergabe.de doesn't
        # have that lag.
        env["PIPELINE_TARGET_DATE"] = date.today().isoformat()

        # Speed: CPV45_Eforms_Attachments_Pipeline.py's own default (also an
        # env var it already reads -- not something this route edits into
        # the file) fetches and OCRs the real attachment PDF for every
        # matched notice, one HTTP request at a time with a polite ~1s
        # delay each, from whatever platform each notice happens to link to
        # (RIB, DTVP, eVergabe, ...). That's what makes a full refresh take
        # minutes: it's built for populating documentContents (full tender
        # text), which nothing on this Dashboard currently reads or
        # displays -- buyer, price, deadline and the notice link all come
        # from the notice metadata, parsed either way. Skipping it here
        # only affects Dashboard-triggered refreshes; a full pipeline run
        # from the command line (no override in its own environment) still
        # downloads attachments as usual. Deliberately NOT touching
        # CPV45_REQUEST_DELAY_SECONDS or TED's own PDF delay/retry
        # settings -- those are there to avoid hammering the source sites,
        # and speeding this up shouldn't come at their expense.
        env.setdefault("CPV45_DOWNLOAD_ATTACHMENTS", "false")

        output_lines: list[str] = []
        timed_out = False
        process: subprocess.Popen[str] | None = None

        def _kill_on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            if process is not None:
                process.kill()

        timer = threading.Timer(REFRESH_TIMEOUT_SECONDS, _kill_on_timeout)
        try:
            # Popen + streaming (instead of subprocess.run(capture_output=True))
            # so the pipeline's own progress prints show up live in this
            # server's console while a refresh is in flight, instead of being
            # silently buffered until the whole multi-minute run finishes.
            process = subprocess.Popen(
                [sys.executable, str(RUN_PIPELINES_SCRIPT), "--import-db"],
                cwd=BACKEND_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            timer.start()
            assert process.stdout is not None
            for line in process.stdout:
                # Relaying the pipeline's own progress output live, the same
                # way it'd print if you ran it from a terminal yourself --
                # this is operator-visible progress, not app logging.
                print(f"[bids refresh] {line}", end="", flush=True)  # noqa: T201
                output_lines.append(line)
            returncode = process.wait()
            timer.cancel()

            if timed_out:
                state.status = "error"
                state.last_error = f"Refresh timed out after {REFRESH_TIMEOUT_SECONDS}s"
                session.add(state)
                session.commit()
                return

            if returncode != 0:
                tail = "".join(output_lines).strip()
                state.status = "error"
                state.last_error = tail[-2000:] or f"exited with code {returncode}"
                session.add(state)
                session.commit()
                return

            if previous_new_since_at is None:
                # First refresh ever: establish the baseline, don't flag
                # everything already in the DB as "new".
                new_count = 0
            else:
                count_statement = (
                    select(func.count())
                    .select_from(Contract)
                    .where(col(Contract.created_at) > previous_new_since_at)
                )
                new_count = session.exec(count_statement).one()

            state.status = "idle"
            state.last_refreshed_at = get_datetime_utc()
            state.new_since_at = started_at
            # Kept as a record of what this particular run found; the
            # dashboard itself now reads live_new_count() instead (see its
            # docstring) so it stays correct even when the DB changes
            # outside of a Refresh click.
            state.last_new_count = new_count
            state.last_error = None
            session.add(state)
            session.commit()

        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            timer.cancel()
            state.status = "error"
            state.last_error = str(exc)
            session.add(state)
            session.commit()


# --- routes -------------------------------------------------------------


@router.get("/", response_model=BidsPublic)
def read_bids(
    session: SessionDep,
    source: Literal["all", "ted", "oeffentlichevergabe"] = "all",
) -> Any:
    """List bids for the Dashboard table: pinned bids first, then the rest,
    each group ordered most-recently-scraped first."""
    statement = select(Contract)
    if source != "all":
        statement = statement.where(Contract.source_system == SOURCE_FILTER_MAP[source])
    contracts = session.exec(statement).all()

    state = get_or_create_state(session)
    pin_rows = session.exec(select(BidPin)).all()
    pinned_at_by_id = {row.contract_id: row.pinned_at for row in pin_rows}

    pinned = sorted(
        (c for c in contracts if c.id in pinned_at_by_id),
        key=lambda c: pinned_at_by_id[c.id],
        reverse=True,  # most recently pinned first
    )
    unpinned = sorted(
        (c for c in contracts if c.id not in pinned_at_by_id),
        key=lambda c: c.created_at,
        reverse=True,  # most recently scraped first
    )
    ordered = pinned + unpinned

    data = [
        contract_to_public(
            c, pinned=c.id in pinned_at_by_id, new_since_at=state.new_since_at
        )
        for c in ordered
    ]
    return BidsPublic(data=data, count=len(data))


@router.post("/{id}/pin", response_model=Message)
def pin_bid(session: SessionDep, id: uuid.UUID) -> Message:
    contract = session.get(Contract, id)
    if not contract:
        raise HTTPException(status_code=404, detail="Bid not found")
    if not session.get(BidPin, id):
        session.add(BidPin(contract_id=id))
        session.commit()
    return Message(message="Bid pinned")


@router.delete("/{id}/pin", response_model=Message)
def unpin_bid(session: SessionDep, id: uuid.UUID) -> Message:
    pin = session.get(BidPin, id)
    if pin:
        session.delete(pin)
        session.commit()
    return Message(message="Bid unpinned")


@router.post("/refresh", response_model=RefreshStatusPublic)
def refresh_bids(session: SessionDep, background_tasks: BackgroundTasks) -> Any:
    state = get_or_create_state(session)

    if state.status == "running":
        stale = (
            state.started_at is not None
            and (get_datetime_utc() - state.started_at).total_seconds()
            > STALE_RUNNING_AFTER_SECONDS
        )
        if not stale:
            return to_status_public(
                session, state, message="A refresh is already running."
            )

    started_at = get_datetime_utc()
    previous_new_since_at = state.new_since_at
    state.status = "running"
    state.started_at = started_at
    state.last_error = None
    session.add(state)
    session.commit()
    session.refresh(state)

    background_tasks.add_task(_run_refresh, started_at, previous_new_since_at)
    return to_status_public(session, state, message="Refresh started.")


@router.get("/refresh/status", response_model=RefreshStatusPublic)
def refresh_status(session: SessionDep) -> Any:
    state = get_or_create_state(session)
    return to_status_public(session, state)
