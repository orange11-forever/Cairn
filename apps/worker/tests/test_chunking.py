import random
from typing import cast

import cairn_worker.chunking as chunking_module
import pytest
from cairn_api.knowledge.schemas import TextLocator
from cairn_worker.chunking import (
    ChunkDraft,
    ChunkingConfig,
    build_chunks,
    normalize_chunk_text,
)
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, ParsedBlock


def test_chunking_config_reads_the_active_profile_contract() -> None:
    """Break caught: valid active-profile limits must reach the chunking boundary."""
    config = ChunkingConfig.from_profile(
        {"maxCodepoints": 1800, "overlapCodepoints": 180}
    )

    assert config == ChunkingConfig(max_codepoints=1800, overlap_codepoints=180)


@pytest.mark.parametrize(
    "profile",
    [
        {"overlapCodepoints": 180},
        {"maxCodepoints": 1800},
        {"maxCodepoints": "1800", "overlapCodepoints": 180},
        {"maxCodepoints": 1800, "overlapCodepoints": "180"},
        {"maxCodepoints": 1800.0, "overlapCodepoints": 180},
        {"maxCodepoints": 1800, "overlapCodepoints": 180.0},
        {"maxCodepoints": True, "overlapCodepoints": 0},
        {"maxCodepoints": 1800, "overlapCodepoints": False},
        {"maxCodepoints": 0, "overlapCodepoints": 0},
        {"maxCodepoints": -1, "overlapCodepoints": 0},
        {"maxCodepoints": 1800, "overlapCodepoints": -1},
        {"maxCodepoints": 1800, "overlapCodepoints": 1800},
        {"maxCodepoints": 1800, "overlapCodepoints": 1801},
    ],
    ids=(
        "missing-maximum",
        "missing-overlap",
        "string-maximum",
        "string-overlap",
        "float-maximum",
        "float-overlap",
        "boolean-maximum",
        "boolean-overlap",
        "zero-maximum",
        "negative-maximum",
        "negative-overlap",
        "equal-overlap",
        "greater-overlap",
    ),
)
def test_chunking_config_rejects_invalid_profiles_without_echoing_values(
    profile: dict[str, object],
) -> None:
    """Break caught: malformed profile values must not control limits or leak."""
    with pytest.raises(ValueError) as caught:
        ChunkingConfig.from_profile(profile)

    assert caught.value.args == ("invalid chunking profile",)
    assert not any(str(value) in str(caught.value) for value in profile.values())


@pytest.mark.parametrize(
    "config",
    [
        ChunkingConfig(max_codepoints=0, overlap_codepoints=0),
        ChunkingConfig(max_codepoints=10, overlap_codepoints=-1),
        ChunkingConfig(max_codepoints=10, overlap_codepoints=10),
        ChunkingConfig(max_codepoints=cast(int, True), overlap_codepoints=0),
        ChunkingConfig(max_codepoints=10, overlap_codepoints=cast(int, False)),
        ChunkingConfig(max_codepoints=cast(int, "10"), overlap_codepoints=0),
        ChunkingConfig(max_codepoints=10, overlap_codepoints=cast(int, 1.0)),
    ],
    ids=(
        "zero-maximum",
        "negative-overlap",
        "equal-overlap",
        "boolean-maximum",
        "boolean-overlap",
        "string-maximum",
        "float-overlap",
    ),
)
def test_build_chunks_rejects_invalid_caller_supplied_config(
    config: ChunkingConfig,
) -> None:
    """Break caught: bypassing profile parsing must not bypass chunking invariants."""
    with pytest.raises(ValueError) as caught:
        build_chunks([], config)

    assert caught.value.args == ("invalid chunking profile",)


def test_small_blocks_remain_separate_and_preserve_parser_truth() -> None:
    """Break caught: chunking must not merge structural blocks or replace citations."""
    first_locator = TextLocator(
        type="text", headingPath=["First"], lineStart=1, lineEnd=2
    )
    second_locator = TextLocator(
        type="text", headingPath=["Second"], lineStart=3, lineEnd=3
    )
    blocks = [
        ParsedBlock(
            kind=BlockKind.HEADING,
            text="First heading",
            locator=first_locator,
        ),
        ParsedBlock(
            kind=BlockKind.PARAGRAPH,
            text="Second paragraph",
            locator=second_locator,
        ),
    ]

    chunks = build_chunks(
        blocks, ChunkingConfig(max_codepoints=100, overlap_codepoints=10)
    )

    assert chunks == [
        ChunkDraft(
            ordinal=0,
            kind=BlockKind.HEADING,
            text="First heading",
            normalized_text="first heading",
            locator=first_locator,
        ),
        ChunkDraft(
            ordinal=1,
            kind=BlockKind.PARAGRAPH,
            text="Second paragraph",
            normalized_text="second paragraph",
            locator=second_locator,
        ),
    ]
    assert chunks[0].locator is first_locator
    assert chunks[1].locator is second_locator


def test_chunk_normalization_is_search_friendly_without_rewriting_display_text() -> None:
    """Break caught: normalization must not overwrite human-readable source text."""
    source_text = "  ＡＢＣ\tStraße\n中文  "
    locator = TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=2)

    chunks = build_chunks(
        [ParsedBlock(kind=BlockKind.TEXT, text=source_text, locator=locator)],
        ChunkingConfig(max_codepoints=100, overlap_codepoints=10),
    )

    assert normalize_chunk_text(source_text) == "abc strasse 中文"
    assert chunks[0].text == source_text
    assert chunks[0].normalized_text == "abc strasse 中文"


def test_oversized_block_prefers_the_rightmost_newline_boundary() -> None:
    """Break caught: a later newline must preserve the largest bounded structure."""
    locator = TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=2)
    block = ParsedBlock(
        kind=BlockKind.PARAGRAPH,
        text="alpha\nbeta\ngamma delta",
        locator=locator,
    )

    chunks = build_chunks(
        [block], ChunkingConfig(max_codepoints=16, overlap_codepoints=2)
    )

    assert [chunk.text for chunk in chunks] == [
        "alpha\nbeta",
        "ta\ngamma delta",
    ]


def test_oversized_block_uses_rightmost_whitespace_then_hard_boundary() -> None:
    """Break caught: splitting must prefer words but bound unspaced CJK input."""
    ascii_locator = TextLocator(
        type="text", headingPath=["ASCII"], lineStart=1, lineEnd=1
    )
    cjk_locator = TextLocator(
        type="text", headingPath=["CJK"], lineStart=2, lineEnd=2
    )

    ascii_chunks = build_chunks(
        [
            ParsedBlock(
                kind=BlockKind.TEXT,
                text="one two three",
                locator=ascii_locator,
            )
        ],
        ChunkingConfig(max_codepoints=9, overlap_codepoints=2),
    )
    cjk_chunks = build_chunks(
        [
            ParsedBlock(
                kind=BlockKind.TEXT,
                text="甲乙丙丁戊己庚辛",
                locator=cjk_locator,
            )
        ],
        ChunkingConfig(max_codepoints=5, overlap_codepoints=2),
    )

    assert [chunk.text for chunk in ascii_chunks] == ["one two", "wo three"]
    assert [chunk.text for chunk in cjk_chunks] == ["甲乙丙丁戊", "丁戊己庚辛"]


def test_separator_that_cannot_advance_past_overlap_uses_hard_boundary() -> None:
    """Break caught: an early separator must not cause an overlap loop."""
    locator = TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=1)

    chunks = build_chunks(
        [ParsedBlock(kind=BlockKind.CODE, text="a bcdef", locator=locator)],
        ChunkingConfig(max_codepoints=4, overlap_codepoints=3),
    )

    assert [chunk.text for chunk in chunks] == ["a bc", "bcd", "bcde", "cdef"]
    assert all(chunk.text for chunk in chunks)
    assert all(len(chunk.text) <= 4 for chunk in chunks)


def test_overlap_is_bounded_inside_each_source_block_and_preserves_structure() -> None:
    """Break caught: overlap must never borrow text or citation truth across blocks."""
    first_locator = TextLocator(
        type="text", headingPath=["First"], lineStart=1, lineEnd=1
    )
    second_locator = TextLocator(
        type="text", headingPath=["Second"], lineStart=2, lineEnd=2
    )
    blocks = [
        ParsedBlock(
            kind=BlockKind.PARAGRAPH,
            text="甲乙丙丁戊己庚辛",
            locator=first_locator,
        ),
        ParsedBlock(
            kind=BlockKind.CODE,
            text="abcdefgh",
            locator=second_locator,
        ),
    ]
    config = ChunkingConfig(max_codepoints=5, overlap_codepoints=2)

    chunks = build_chunks(blocks, config)

    assert [chunk.text for chunk in chunks] == [
        "甲乙丙丁戊",
        "丁戊己庚辛",
        "abcde",
        "defgh",
    ]
    assert [chunk.kind for chunk in chunks] == [
        BlockKind.PARAGRAPH,
        BlockKind.PARAGRAPH,
        BlockKind.CODE,
        BlockKind.CODE,
    ]
    assert [chunk.locator for chunk in chunks] == [
        first_locator,
        first_locator,
        second_locator,
        second_locator,
    ]
    assert all(chunk.locator is first_locator for chunk in chunks[:2])
    assert all(chunk.locator is second_locator for chunk in chunks[2:])
    assert chunks[0].text[-2:] == chunks[1].text[:2]
    assert chunks[2].text[-2:] == chunks[3].text[:2]


def test_repeated_chunking_is_equal_with_sequential_zero_based_ordinals() -> None:
    """Break caught: equal parser output must not produce unstable index identities."""
    locator = TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=1)
    blocks = [
        ParsedBlock(
            kind=BlockKind.TEXT,
            text="甲乙丙丁戊己庚辛",
            locator=locator,
        )
    ]
    config = ChunkingConfig(max_codepoints=5, overlap_codepoints=2)

    first = build_chunks(blocks, config)
    second = build_chunks(blocks, config)

    assert first == second
    assert [chunk.ordinal for chunk in first] == [0, 1]


def test_chunk_output_limit_raises_a_permanent_bounded_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: adversarial overlap must not create unbounded indexing work."""
    monkeypatch.setattr(chunking_module, "MAX_CHUNKS_PER_DOCUMENT", 2)
    locator = TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=1)
    source_text = "secretxy"

    with pytest.raises(WorkerFailure) as caught:
        build_chunks(
            [ParsedBlock(kind=BlockKind.TEXT, text=source_text, locator=locator)],
            ChunkingConfig(max_codepoints=3, overlap_codepoints=0),
        )

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"
    assert source_text not in caught.value.safe_detail
    assert "3" not in caught.value.safe_detail


def test_fixed_seed_mixed_text_always_produces_stable_bounded_drafts() -> None:
    """Break caught: arbitrary mixed text must terminate without unstable or empty drafts."""
    generator = random.Random(0)
    alphabet = "abcXYZ \t\n甲乙丙"
    config = ChunkingConfig(max_codepoints=12, overlap_codepoints=3)

    for case in range(100):
        text = "".join(
            generator.choice(alphabet) for _ in range(generator.randint(1, 80))
        )
        if not text.strip():
            text += "甲"
        locator = TextLocator(
            type="text", headingPath=[f"Case {case}"], lineStart=1, lineEnd=1
        )
        blocks = [ParsedBlock(kind=BlockKind.TEXT, text=text, locator=locator)]

        first = build_chunks(blocks, config)
        second = build_chunks(blocks, config)

        assert first == second
        assert first
        assert [chunk.ordinal for chunk in first] == list(range(len(first)))
        assert all(chunk.text for chunk in first)
        assert all(chunk.normalized_text for chunk in first)
        assert all(len(chunk.text) <= 12 for chunk in first)
        assert all(chunk.locator is locator for chunk in first)
