from datetime import date

from sqlmodel import Session, select

from app.models import Company, Filing, FinancialFact
from app.services.edgar import EdgarClient

# Facts and filing-comparison chaining only matter for periodic financial
# reports; 8-Ks, ownership forms (3/4/5), and proxy statements etc. are
# skipped so `previous_filing_id` chains "the last 10-Q" not "the last
# filing of any kind".
_TRACKED_FORM_TYPES = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


class FilingIngestionService:
    """Syncs a company's SEC EDGAR filing history and structured XBRL facts into the database.

    Idempotent: re-running for a company already ingested only adds
    filings/facts that aren't there yet, keyed on SEC's own identifiers
    (accession_number, and filing_id+concept+unit+period_end).
    """

    def __init__(self, session: Session, edgar_client: EdgarClient | None = None) -> None:
        self.session = session
        self.edgar = edgar_client or EdgarClient()

    def sync_company(self, cik: str | int) -> Company:
        cik_padded = EdgarClient.normalize_cik(cik)
        submissions = self.edgar.get_submissions(cik_padded)
        company = self._upsert_company(cik_padded, submissions)
        self._sync_filings(company, submissions)
        self._sync_facts(company)
        return company

    def _upsert_company(self, cik: str, submissions: dict[str, object]) -> Company:
        company = self.session.exec(select(Company).where(Company.cik == cik)).first()
        tickers = submissions.get("tickers") or []
        ticker = tickers[0] if isinstance(tickers, list) and tickers else None
        sic_code = submissions.get("sic")
        name = str(submissions["name"])
        if company is None:
            company = Company(
                cik=cik,
                name=name,
                ticker=ticker,
                sic_code=str(sic_code) if sic_code else None,
            )
            self.session.add(company)
        else:
            company.name = name
            company.ticker = ticker
            company.sic_code = str(sic_code) if sic_code else None
            self.session.add(company)
        self.session.commit()
        self.session.refresh(company)
        return company

    def _sync_filings(self, company: Company, submissions: dict[str, object]) -> None:
        filings_obj = submissions["filings"]
        assert isinstance(filings_obj, dict)
        recent = filings_obj["recent"]
        assert isinstance(recent, dict)
        rows = list(
            zip(
                recent["accessionNumber"],
                recent["form"],
                recent["filingDate"],
                recent["reportDate"],
                recent["primaryDocument"],
                strict=True,
            )
        )
        # SEC returns newest-first; walk oldest-first so previous_filing_id
        # chaining only ever looks backward at already-ingested filings.
        rows.reverse()

        last_filing_by_form: dict[str, Filing] = {}
        for accession_number, form_type, filing_date_str, report_date_str, primary_document in rows:
            if form_type not in _TRACKED_FORM_TYPES:
                continue
            filing = self.session.exec(
                select(Filing).where(Filing.accession_number == accession_number)
            ).first()
            previous = last_filing_by_form.get(form_type)
            if filing is None:
                filing = Filing(
                    accession_number=accession_number,
                    company_id=company.id,
                    form_type=form_type,
                    filing_date=date.fromisoformat(filing_date_str),
                    period_of_report=date.fromisoformat(report_date_str) if report_date_str else None,
                    previous_filing_id=previous.id if previous else None,
                    primary_document=primary_document,
                )
                self.session.add(filing)
                self.session.commit()
                self.session.refresh(filing)
            elif filing.primary_document is None and primary_document:
                # Backfills a field added after this filing was first ingested.
                filing.primary_document = primary_document
                self.session.add(filing)
                self.session.commit()
                self.session.refresh(filing)
            last_filing_by_form[form_type] = filing

    def _sync_facts(self, company: Company) -> None:
        facts_data = self.edgar.get_company_facts(company.cik)
        filings_by_accession = {
            filing.accession_number: filing
            for filing in self.session.exec(select(Filing).where(Filing.company_id == company.id))
        }
        existing_keys = {
            (fact.filing_id, fact.concept, fact.unit, fact.period_end)
            for fact in self.session.exec(
                select(FinancialFact).join(Filing).where(Filing.company_id == company.id)
            )
        }

        new_facts: list[FinancialFact] = []
        facts_by_taxonomy = facts_data.get("facts", {})
        assert isinstance(facts_by_taxonomy, dict)
        for taxonomy, concepts in facts_by_taxonomy.items():
            for concept, concept_data in concepts.items():
                for unit, entries in concept_data.get("units", {}).items():
                    for entry in entries:
                        filing = filings_by_accession.get(entry["accn"])
                        if filing is None:
                            continue  # fact was reported on a filing type we don't track
                        period_end = date.fromisoformat(entry["end"])
                        key = (filing.id, concept, unit, period_end)
                        if key in existing_keys:
                            continue
                        existing_keys.add(key)
                        new_facts.append(
                            FinancialFact(
                                filing_id=filing.id,
                                taxonomy=taxonomy,
                                concept=concept,
                                unit=unit,
                                value=float(entry["val"]),
                                fiscal_year=entry.get("fy"),
                                fiscal_period=entry.get("fp"),
                                period_start=date.fromisoformat(entry["start"]) if "start" in entry else None,
                                period_end=period_end,
                            )
                        )
        self.session.add_all(new_facts)
        self.session.commit()
