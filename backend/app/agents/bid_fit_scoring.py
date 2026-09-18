from pydantic import BaseModel, Field

RED = "red"
YELLOW = "yellow"
GREEN = "green"

# Lower ranks first: green beats yellow beats red, regardless of how much
# higher a red bid's similarity_score is — similarity only breaks ties
# within the same flag, it never outranks a better flag.
_FLAG_RANK = {GREEN: 0, YELLOW: 1, RED: 2}


class HardlinerViolation(BaseModel):
    """One hardliner checked against the bid, with the LLM's verdict."""

    hardliner: str
    violated: bool
    reason: str = Field(
        description="Why the bid does or doesn't satisfy this hardliner, "
        "grounded in the retrieved bid context."
    )
    solution: str | None = Field(
        default=None,
        description="A concrete way to resolve the violation, if one "
        "realistically exists (e.g. subcontracting a missing capability). "
        "Omit if no viable solution exists.",
    )
    solution_is_realistic: bool = Field(
        default=False,
        description="False whenever `solution` is None, and also False if "
        "a proposed solution is impractical, too costly, or otherwise "
        "shouldn't count (e.g. 'get certified in two weeks' for a "
        "six-month certification process, or anything that would still "
        "break a non-negotiable hardliner).",
    )


class BidFitScore(BaseModel):
    """Final verdict for one bid against one company profile.

    `flag` is the go/no-go signal and is decided purely from the hardliner
    violations — it never blends in similarity, so a topically "similar"
    bid can never talk its way past an unresolved dealbreaker:

    - red: at least one violated hardliner has no realistic solution —
      not worth pursuing.
    - yellow: every violation has a realistic solution — workable, but
      flag the mitigations needed.
    - green: no hardliner is violated at all.

    `similarity_score` (0-1 cosine similarity between the company's
    profile/hardliners and the retrieved bid context) is reported
    separately, purely to rank bids that share the same flag — it's not a
    fit signal on its own.
    """

    flag: str
    similarity_score: float
    hard_blockers: list[str]
    soft_issues: list[str]


def score_bid_fit(
    violations: list[HardlinerViolation], similarity_score: float
) -> BidFitScore:
    hard_blockers = [
        v.hardliner
        for v in violations
        if v.violated and not (v.solution and v.solution_is_realistic)
    ]
    soft_issues = [
        v.hardliner
        for v in violations
        if v.violated and v.solution and v.solution_is_realistic
    ]

    if hard_blockers:
        flag = RED
    elif soft_issues:
        flag = YELLOW
    else:
        flag = GREEN

    return BidFitScore(
        flag=flag,
        similarity_score=round(similarity_score, 4),
        hard_blockers=hard_blockers,
        soft_issues=soft_issues,
    )


def rank_bid_fits(results: list[BidFitScore]) -> list[BidFitScore]:
    """Rank scored bids best-first: green beats yellow beats red, no
    matter the similarity_score on either side. Ties within the same flag
    are broken by similarity_score, higher first."""
    return sorted(results, key=lambda r: (_FLAG_RANK[r.flag], -r.similarity_score))
