import uuid
from datetime import date

from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.models import (
    Company,
    CompanyPublic,
    Filing,
    NarrativeChange,
    NarrativeChangePublic,
)
from app.services.edgar import EdgarClient
from app.services.signals import FilingSignals, StructuredRiskFlags, get_filing_signals, get_structured_risk_flags


class FilingTimelineEntry(BaseModel):
    filing_id: uuid.UUID
    accession_number: str
    form_type: str
    filing_date: date
    period_of_report: date | None
    signals: FilingSignals | None
    narrative_changes: list[NarrativeChangePublic]
    # Only populated on the newest filing — the dilution/margin/capital-
    # efficiency trends behind this look back across several filings, so
    # computing it per historical entry would multiply DB queries for a
    # view of the past you're less likely to check.
    structured_risk_flags: StructuredRiskFlags | None


class CompanyTimeline(BaseModel):
    company: CompanyPublic
    filings: list[FilingTimelineEntry]


def get_company_timeline(session: Session, cik: str) -> CompanyTimeline | None:
    """Every ingested filing for a company, newest first, each carrying its
    structured-facts signals (computed fresh — cheap, no external calls) and
    whatever narrative changes have already been computed for it via
    POST /ingestion/filings/{id}/narrative-diff (not triggered here — that
    call is slow, local-LLM-bound, and left as an explicit user action)."""
    cik_padded = EdgarClient.normalize_cik(cik)
    company = session.exec(select(Company).where(Company.cik == cik_padded)).first()
    if company is None:
        return None

    filings = session.exec(
        select(Filing).where(Filing.company_id == company.id).order_by(col(Filing.filing_date).desc())
    ).all()

    entries: list[FilingTimelineEntry] = []
    for index, filing in enumerate(filings):
        signals = get_filing_signals(session, filing) if filing.previous_filing_id else None
        changes = session.exec(select(NarrativeChange).where(NarrativeChange.filing_id == filing.id)).all()
        entries.append(
            FilingTimelineEntry(
                filing_id=filing.id,
                accession_number=filing.accession_number,
                form_type=filing.form_type,
                filing_date=filing.filing_date,
                period_of_report=filing.period_of_report,
                signals=signals,
                narrative_changes=[NarrativeChangePublic.model_validate(c) for c in changes],
                structured_risk_flags=get_structured_risk_flags(session, filing) if index == 0 else None,
            )
        )

    return CompanyTimeline(company=CompanyPublic.model_validate(company), filings=entries)
