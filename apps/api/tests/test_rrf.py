from uuid import UUID

from cairn_api.knowledge.search_service import RankedCandidate, reciprocal_rank_fusion


def test_rrf_sums_one_based_ranks_deduplicates_and_stably_breaks_ties() -> None:
    """Break caught: zero-based scoring, duplicate inflation, or unstable UUID tie ordering."""
    first = UUID("00000000-0000-4000-8000-000000000001")
    second = UUID("00000000-0000-4000-8000-000000000002")
    third = UUID("00000000-0000-4000-8000-000000000003")

    result = reciprocal_rank_fusion(
        [RankedCandidate(second, 1), RankedCandidate(first, 2), RankedCandidate(first, 3)],
        [RankedCandidate(third, 1), RankedCandidate(first, 2)],
        limit=3,
    )

    assert result == [
        (first, 2 / 62),
        (second, 1 / 61),
        (third, 1 / 61),
    ]


def test_rrf_limit_is_applied_after_fusion() -> None:
    """Break caught: truncating a source before fusion changes the combined winner."""
    first = UUID("00000000-0000-4000-8000-000000000001")
    second = UUID("00000000-0000-4000-8000-000000000002")

    assert reciprocal_rank_fusion(
        [RankedCandidate(first, 1), RankedCandidate(second, 2)],
        [RankedCandidate(second, 1)],
        limit=1,
    ) == [(second, (1 / 62) + (1 / 61))]
