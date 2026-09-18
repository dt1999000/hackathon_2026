from app.agents.bid_fit_scoring import (
    BidFitScore,
    HardlinerViolation,
    pick_flag_examples,
    rank_bid_fits,
    score_bid_fit,
)


def _score(flag: str, similarity_score: float) -> BidFitScore:
    return BidFitScore(flag=flag, similarity_score=similarity_score, hard_blockers=[], soft_issues=[])


def _violation(
    violated: bool, solution: str | None = None, solution_is_realistic: bool = False
) -> HardlinerViolation:
    return HardlinerViolation(
        hardliner="test hardliner",
        violated=violated,
        reason="because",
        solution=solution,
        solution_is_realistic=solution_is_realistic,
    )


def test_no_violations_is_green() -> None:
    result = score_bid_fit([_violation(False), _violation(False)], similarity_score=0.4)
    assert result.flag == "green"
    assert result.hard_blockers == []
    assert result.soft_issues == []
    assert result.similarity_score == 0.4


def test_violation_with_realistic_solution_is_yellow() -> None:
    result = score_bid_fit(
        [_violation(True, solution="subcontract it", solution_is_realistic=True)],
        similarity_score=0.0,
    )
    assert result.flag == "yellow"
    assert result.hard_blockers == []
    assert result.soft_issues == ["test hardliner"]


def test_unsolved_violation_is_red_regardless_of_similarity() -> None:
    """A perfect topical match can't buy back a hardliner with no fix."""
    with_bad_match = score_bid_fit([_violation(True)], similarity_score=0.0)
    with_perfect_match = score_bid_fit([_violation(True)], similarity_score=1.0)

    assert with_bad_match.flag == "red"
    assert with_bad_match.hard_blockers == ["test hardliner"]
    assert with_perfect_match.flag == "red"


def test_unrealistic_solution_counts_as_no_solution() -> None:
    result = score_bid_fit(
        [_violation(True, solution="get certified in two weeks", solution_is_realistic=False)],
        similarity_score=0.9,
    )
    assert result.flag == "red"
    assert result.hard_blockers == ["test hardliner"]


def test_one_hard_blocker_outranks_any_number_of_soft_issues() -> None:
    many_soft = [
        _violation(True, solution="fix it", solution_is_realistic=True) for _ in range(3)
    ]
    one_hard_among_many_soft = [*many_soft, _violation(True)]

    soft_only = score_bid_fit(many_soft, similarity_score=0.0)
    mixed = score_bid_fit(one_hard_among_many_soft, similarity_score=1.0)

    assert soft_only.flag == "yellow"
    # A single unresolved violation still makes the whole bid red, even
    # alongside several resolvable ones and a perfect similarity score.
    assert mixed.flag == "red"


def test_rank_bid_fits_puts_green_before_yellow_before_red() -> None:
    red = _score("red", similarity_score=1.0)
    yellow = _score("yellow", similarity_score=0.0)
    green = _score("green", similarity_score=0.0)

    assert rank_bid_fits([red, yellow, green]) == [green, yellow, red]


def test_rank_bid_fits_breaks_ties_within_a_flag_by_similarity() -> None:
    low = _score("yellow", similarity_score=0.2)
    high = _score("yellow", similarity_score=0.9)

    assert rank_bid_fits([low, high]) == [high, low]


def test_rank_bid_fits_never_lets_similarity_beat_a_better_flag() -> None:
    """A perfect-similarity red still ranks below a zero-similarity green."""
    perfect_red = _score("red", similarity_score=1.0)
    zero_green = _score("green", similarity_score=0.0)

    assert rank_bid_fits([perfect_red, zero_green]) == [zero_green, perfect_red]


def test_pick_flag_examples_takes_two_of_each_color() -> None:
    greens = [_score("green", s) for s in (0.9, 0.4, 0.1)]
    yellows = [_score("yellow", s) for s in (0.8, 0.5, 0.2)]
    reds = [_score("red", s) for s in (0.7, 0.3, 0.05)]

    picked = pick_flag_examples([*reds, *yellows, *greens], per_flag=2)

    assert [r.flag for r in picked] == ["green", "green", "yellow", "yellow", "red", "red"]
    assert [r.similarity_score for r in picked] == [0.9, 0.4, 0.8, 0.5, 0.7, 0.3]


def test_pick_flag_examples_skips_a_flag_that_has_no_bids() -> None:
    greens = [_score("green", 0.9), _score("green", 0.2)]
    reds = [_score("red", 0.5)]

    picked = pick_flag_examples([*greens, *reds], per_flag=2)

    assert [r.flag for r in picked] == ["green", "green", "red"]
    assert picked[-1].similarity_score == 0.5
