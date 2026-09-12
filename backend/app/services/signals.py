from datetime import date

from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.models import Filing, FinancialFact

# XBRL concept name candidates, most preferred first — companies sometimes
# use a different tag for the same underlying line item.
_DEBT_CONCEPTS = ["LongTermDebtNoncurrent", "LongTermDebt"]
_DEBT_CURRENT_CONCEPTS = ["LongTermDebtCurrent"]
_CASH_CONCEPTS = ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalentsAtFairValue"]
_CURRENT_ASSETS_CONCEPTS = ["AssetsCurrent"]
_CURRENT_LIABILITIES_CONCEPTS = ["LiabilitiesCurrent"]
_CAPEX_CONCEPTS = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForCapitalImprovements"]
_SHARE_COUNT_CONCEPTS = ["CommonStockSharesOutstanding"]
_SBC_CONCEPTS = ["ShareBasedCompensation"]
_OPERATING_CASH_FLOW_CONCEPTS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
_REVENUE_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
_COGS_CONCEPTS = ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"]
_GROSS_PROFIT_CONCEPTS = ["GrossProfit"]


class MetricChange(BaseModel):
    metric: str
    unit: str
    current_value: float | None
    previous_value: float | None
    change: float | None
    change_pct: float | None


class FilingSignals(BaseModel):
    filing_id: str
    previous_filing_id: str | None
    debt_and_liquidity: list[MetricChange]
    capex: MetricChange


class DilutionPeriod(BaseModel):
    filing_id: str
    period_end: date | None
    share_count: float | None
    share_count_change_pct: float | None
    sbc: float | None
    operating_cash_flow: float | None
    sbc_pct_of_operating_cash_flow: float | None


class DilutionTrend(BaseModel):
    filing_id: str
    periods: list[DilutionPeriod]


class GrossMarginPeriod(BaseModel):
    filing_id: str
    period_end: date | None
    revenue: float | None
    revenue_change_pct: float | None
    gross_profit: float | None
    gross_margin_pct: float | None
    gross_margin_change_pct_points: float | None  # percentage-point change, not a relative %
    margin_compressed_while_revenue_grew: bool | None


class GrossMarginTrend(BaseModel):
    filing_id: str
    periods: list[GrossMarginPeriod]


def _get_instant_fact(session: Session, filing: Filing, concepts: list[str]) -> FinancialFact | None:
    """Balance-sheet ("instant") fact as of a filing's period_of_report.

    Instant facts (debt, cash, current assets/liabilities balances) carry no
    period_start in EDGAR's data — only a single point-in-time `end`.
    """
    if filing.period_of_report is None:
        return None
    for concept in concepts:
        fact = session.exec(
            select(FinancialFact)
            .where(FinancialFact.filing_id == filing.id)
            .where(FinancialFact.concept == concept)
            .where(FinancialFact.period_end == filing.period_of_report)
            .where(col(FinancialFact.period_start).is_(None))
        ).first()
        if fact is not None:
            return fact
    return None


def _get_duration_fact(session: Session, filing: Filing, concepts: list[str]) -> FinancialFact | None:
    """Cash-flow ("duration") fact ending on a filing's period_of_report.

    A 10-Q can carry more than one duration for the same concept (the
    quarter-only figure and the cumulative fiscal-year-to-date figure);
    EDGAR always includes the cumulative one, so the longest span wins.
    """
    if filing.period_of_report is None:
        return None
    for concept in concepts:
        facts = session.exec(
            select(FinancialFact)
            .where(FinancialFact.filing_id == filing.id)
            .where(FinancialFact.concept == concept)
            .where(FinancialFact.period_end == filing.period_of_report)
            .where(col(FinancialFact.period_start).is_not(None))
        ).all()
        best: FinancialFact | None = None
        best_days = -1
        for fact in facts:
            if fact.period_start is None or fact.period_end is None:
                continue
            days = (fact.period_end - fact.period_start).days
            if days > best_days:
                best = fact
                best_days = days
        if best is not None:
            return best
    return None


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def _build_metric_change(
    metric: str, fact: FinancialFact | None, previous_fact: FinancialFact | None
) -> MetricChange:
    current_value = fact.value if fact is not None else None
    previous_value = previous_fact.value if previous_fact is not None else None
    unit = fact.unit if fact is not None else (previous_fact.unit if previous_fact is not None else "USD")
    return MetricChange(
        metric=metric,
        unit=unit,
        current_value=current_value,
        previous_value=previous_value,
        change=_delta(current_value, previous_value),
        change_pct=_pct_change(current_value, previous_value),
    )


def _compute_current_ratio(session: Session, filing: Filing) -> float | None:
    assets = _get_instant_fact(session, filing, _CURRENT_ASSETS_CONCEPTS)
    liabilities = _get_instant_fact(session, filing, _CURRENT_LIABILITIES_CONCEPTS)
    if assets is None or liabilities is None or liabilities.value == 0:
        return None
    return assets.value / liabilities.value


def get_debt_and_liquidity_change(session: Session, filing: Filing) -> list[MetricChange]:
    """Debt and liquidity signal vs. the prior filing of the same form_type.

    All inputs are point-in-time balance-sheet figures, so a direct diff
    between consecutive filings is valid without any period normalization.
    """
    if filing.previous_filing_id is None:
        return []
    previous = session.get(Filing, filing.previous_filing_id)
    if previous is None:
        return []

    long_term_debt = _build_metric_change(
        "long_term_debt",
        _get_instant_fact(session, filing, _DEBT_CONCEPTS),
        _get_instant_fact(session, previous, _DEBT_CONCEPTS),
    )
    current_portion_debt = _build_metric_change(
        "current_portion_long_term_debt",
        _get_instant_fact(session, filing, _DEBT_CURRENT_CONCEPTS),
        _get_instant_fact(session, previous, _DEBT_CURRENT_CONCEPTS),
    )
    cash = _build_metric_change(
        "cash_and_equivalents",
        _get_instant_fact(session, filing, _CASH_CONCEPTS),
        _get_instant_fact(session, previous, _CASH_CONCEPTS),
    )
    current_ratio_now = _compute_current_ratio(session, filing)
    current_ratio_prev = _compute_current_ratio(session, previous)
    current_ratio = MetricChange(
        metric="current_ratio",
        unit="ratio",
        current_value=current_ratio_now,
        previous_value=current_ratio_prev,
        change=_delta(current_ratio_now, current_ratio_prev),
        change_pct=_pct_change(current_ratio_now, current_ratio_prev),
    )

    return [long_term_debt, current_portion_debt, cash, current_ratio]


def _capex_daily_rate(session: Session, filing: Filing) -> float | None:
    fact = _get_duration_fact(session, filing, _CAPEX_CONCEPTS)
    if fact is None or fact.period_start is None or fact.period_end is None:
        return None
    days = (fact.period_end - fact.period_start).days
    if days <= 0:
        return None
    return fact.value / days


def get_capex_change(session: Session, filing: Filing) -> MetricChange:
    """Capital-expenditure signal vs. the prior filing of the same form_type.

    EDGAR reports PaymentsToAcquirePropertyPlantAndEquipment as cumulative
    since the start of the fiscal year, so consecutive filings of the same
    form_type can cover different-length periods (e.g. a Q1 10-Q's 3 months
    vs. a Q2 10-Q's 6 months). Comparing raw cumulative totals would read
    "a longer period" as "more capex" — normalizing both to a daily rate
    before comparing avoids that.
    """
    if filing.previous_filing_id is None:
        return MetricChange(
            metric="capex_daily_rate", unit="USD/day", current_value=None, previous_value=None, change=None, change_pct=None
        )
    previous = session.get(Filing, filing.previous_filing_id)
    if previous is None:
        return MetricChange(
            metric="capex_daily_rate", unit="USD/day", current_value=None, previous_value=None, change=None, change_pct=None
        )

    current_rate = _capex_daily_rate(session, filing)
    previous_rate = _capex_daily_rate(session, previous)
    return MetricChange(
        metric="capex_daily_rate",
        unit="USD/day",
        current_value=current_rate,
        previous_value=previous_rate,
        change=_delta(current_rate, previous_rate),
        change_pct=_pct_change(current_rate, previous_rate),
    )


def get_filing_signals(session: Session, filing: Filing) -> FilingSignals:
    return FilingSignals(
        filing_id=str(filing.id),
        previous_filing_id=str(filing.previous_filing_id) if filing.previous_filing_id else None,
        debt_and_liquidity=get_debt_and_liquidity_change(session, filing),
        capex=get_capex_change(session, filing),
    )


def _filing_window(session: Session, filing: Filing, lookback: int) -> list[Filing]:
    """Up to `lookback` filings ending at `filing`, oldest first, walked via
    previous_filing_id — a same-form_type chain, so for 10-Ks this is exact
    year-over-year and for 10-Qs it's exact quarter-over-quarter."""
    window: list[Filing] = [filing]
    current = filing
    while len(window) < lookback and current.previous_filing_id is not None:
        previous = session.get(Filing, current.previous_filing_id)
        if previous is None:
            break
        window.append(previous)
        current = previous
    window.reverse()
    return window


def get_dilution_trend(session: Session, filing: Filing, lookback: int = 3) -> DilutionTrend:
    """Share count and stock-based-compensation trend across up to `lookback`
    consecutive filings of the same form_type, ending at `filing`."""
    window = _filing_window(session, filing, lookback)

    periods: list[DilutionPeriod] = []
    previous_share_count: float | None = None
    for period_filing in window:
        share_count_fact = _get_instant_fact(session, period_filing, _SHARE_COUNT_CONCEPTS)
        sbc_fact = _get_duration_fact(session, period_filing, _SBC_CONCEPTS)
        ocf_fact = _get_duration_fact(session, period_filing, _OPERATING_CASH_FLOW_CONCEPTS)

        share_count = share_count_fact.value if share_count_fact is not None else None
        sbc = sbc_fact.value if sbc_fact is not None else None
        ocf = ocf_fact.value if ocf_fact is not None else None

        periods.append(
            DilutionPeriod(
                filing_id=str(period_filing.id),
                period_end=period_filing.period_of_report,
                share_count=share_count,
                share_count_change_pct=_pct_change(share_count, previous_share_count),
                sbc=sbc,
                operating_cash_flow=ocf,
                sbc_pct_of_operating_cash_flow=(sbc / abs(ocf) * 100) if sbc is not None and ocf else None,
            )
        )
        previous_share_count = share_count

    return DilutionTrend(filing_id=str(filing.id), periods=periods)


def _get_gross_margin_period(session: Session, filing: Filing) -> tuple[float | None, float | None, float | None]:
    """(revenue, gross_profit, revenue_daily_rate) for a filing's period.

    Prefers the filer's own reported GrossProfit tag; falls back to revenue
    minus cost-of-revenue for filers (e.g. SpaceX) that don't tag GrossProfit
    directly. Revenue is also reported as a daily rate — like
    _capex_daily_rate, EDGAR's revenue duration is cumulative since the start
    of the fiscal year, so a Q3 10-Q's 9-month figure and the next Q1 10-Q's
    3-month figure aren't directly comparable without normalizing for period
    length first (raw comparison reads "shorter period" as "revenue fell").
    gross_margin_pct itself doesn't need this: it's a ratio of two figures
    over the same period, so period length cancels out.
    """
    revenue_fact = _get_duration_fact(session, filing, _REVENUE_CONCEPTS)
    if revenue_fact is None:
        return None, None, None
    revenue = revenue_fact.value

    gross_profit_fact = _get_duration_fact(session, filing, _GROSS_PROFIT_CONCEPTS)
    if gross_profit_fact is not None:
        gross_profit = gross_profit_fact.value
    else:
        cogs_fact = _get_duration_fact(session, filing, _COGS_CONCEPTS)
        gross_profit = revenue - cogs_fact.value if cogs_fact is not None else None

    if revenue_fact.period_start is None or revenue_fact.period_end is None:
        return revenue, gross_profit, None
    days = (revenue_fact.period_end - revenue_fact.period_start).days
    revenue_daily_rate = revenue / days if days > 0 else None
    return revenue, gross_profit, revenue_daily_rate


def get_gross_margin_trend(session: Session, filing: Filing, lookback: int = 3) -> GrossMarginTrend:
    """Revenue and gross-margin trend across up to `lookback` consecutive
    filings of the same form_type, ending at `filing`. Flags any period where
    the margin compressed (in percentage points) while revenue still grew —
    a real warning sign distinct from a margin dip during a revenue decline."""
    window = _filing_window(session, filing, lookback)

    periods: list[GrossMarginPeriod] = []
    previous_revenue_daily_rate: float | None = None
    previous_margin_pct: float | None = None
    for period_filing in window:
        revenue, gross_profit, revenue_daily_rate = _get_gross_margin_period(session, period_filing)
        margin_pct = (gross_profit / revenue * 100) if gross_profit is not None and revenue else None
        margin_change = (margin_pct - previous_margin_pct) if margin_pct is not None and previous_margin_pct is not None else None
        revenue_change_pct = _pct_change(revenue_daily_rate, previous_revenue_daily_rate)

        margin_compressed_while_revenue_grew = (
            margin_change < 0 and revenue_change_pct > 0
            if margin_change is not None and revenue_change_pct is not None
            else None
        )

        periods.append(
            GrossMarginPeriod(
                filing_id=str(period_filing.id),
                period_end=period_filing.period_of_report,
                revenue=revenue,
                revenue_change_pct=revenue_change_pct,
                gross_profit=gross_profit,
                gross_margin_pct=margin_pct,
                gross_margin_change_pct_points=margin_change,
                margin_compressed_while_revenue_grew=margin_compressed_while_revenue_grew,
            )
        )
        previous_revenue_daily_rate = revenue_daily_rate
        previous_margin_pct = margin_pct

    return GrossMarginTrend(filing_id=str(filing.id), periods=periods)
