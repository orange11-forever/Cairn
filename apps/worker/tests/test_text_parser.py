import tracemalloc
from io import BytesIO

import pytest
from cairn_api.knowledge.schemas import TextLocator
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, ParserRegistry


def test_text_parser_preserves_utf8_chinese_english_and_exact_lines() -> None:
    """Break caught: UTF-8 BOM, CRLF, and controls must not corrupt searchable text."""
    content = b"\xef\xbb\xbf\r\nHello\r\n\xe4\xb8\xad\xe6\x96\x87\x00\x01\r\n"

    blocks = ParserRegistry().for_media_type("text/plain").parse(BytesIO(content))

    assert len(blocks) == 1
    assert blocks[0].kind is BlockKind.TEXT
    assert blocks[0].text == "Hello\n中文"
    assert blocks[0].locator == TextLocator(
        type="text",
        headingPath=[],
        lineStart=2,
        lineEnd=3,
    )
    assert blocks[0].metadata == {}


@pytest.mark.parametrize("media_type", ["text/plain", "text/markdown"])
def test_text_formats_reject_invalid_utf8_without_leaking_bytes(media_type: str) -> None:
    """Break caught: invalid text encodings must fail safely rather than replace characters."""
    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type(media_type).parse(BytesIO(b"secret\xffcontents"))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert "secret" not in caught.value.safe_detail


def test_markdown_parser_emits_headings_code_and_paragraphs_with_exact_ranges() -> None:
    """Break caught: Markdown structure and heading ancestry must survive deterministic parsing."""
    content = (
        "# 总览\r\n"
        "\r\n"
        "Intro 中文\r\n"
        "\r\n"
        "Details\r\n"
        "=======\r\n"
        "\r\n"
        "```python\r\n"
        '    print("你好")\r\n'
        "```\r\n"
        "\r\n"
        "## Child\r\n"
        "Body"
    ).encode()

    blocks = ParserRegistry().for_media_type("text/markdown").parse(BytesIO(content))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.HEADING, "总览"),
        (BlockKind.PARAGRAPH, "Intro 中文"),
        (BlockKind.HEADING, "Details"),
        (BlockKind.CODE, '    print("你好")'),
        (BlockKind.HEADING, "Child"),
        (BlockKind.PARAGRAPH, "Body"),
    ]
    assert [block.locator for block in blocks] == [
        TextLocator(type="markdown", headingPath=["总览"], lineStart=1, lineEnd=1),
        TextLocator(type="markdown", headingPath=["总览"], lineStart=3, lineEnd=3),
        TextLocator(type="markdown", headingPath=["Details"], lineStart=5, lineEnd=6),
        TextLocator(type="markdown", headingPath=["Details"], lineStart=8, lineEnd=10),
        TextLocator(type="markdown", headingPath=["Details", "Child"], lineStart=12, lineEnd=12),
        TextLocator(type="markdown", headingPath=["Details", "Child"], lineStart=13, lineEnd=13),
    ]
    assert [dict(block.metadata) for block in blocks] == [
        {},
        {},
        {},
        {"language": "python"},
        {},
        {},
    ]


@pytest.mark.parametrize(
    ("opener", "body", "language"),
    [
        ("```python", "---\nvalue", "python"),
        ("~~~javascript", "===\nvalue", "javascript"),
    ],
)
def test_markdown_fence_precedes_setext_lookahead(
    opener: str,
    body: str,
    language: str,
) -> None:
    """Break caught: setext-looking fence content must remain code for both marker types."""
    marker = opener[0] * 3
    content = f"{opener}\n{body}\n{marker}\n\nAfter".encode()

    blocks = ParserRegistry().for_media_type("text/markdown").parse(BytesIO(content))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.CODE, body),
        (BlockKind.PARAGRAPH, "After"),
    ]
    assert blocks[0].metadata == {"language": language}
    assert blocks[0].locator == TextLocator(
        type="markdown",
        headingPath=[],
        lineStart=1,
        lineEnd=4,
    )
    assert blocks[1].locator == TextLocator(
        type="markdown",
        headingPath=[],
        lineStart=6,
        lineEnd=6,
    )


@pytest.mark.parametrize("line_ending", [b"\n", b"\r"], ids=("lf", "cr"))
def test_markdown_heading_bomb_is_rejected_before_block_amplification(
    line_ending: bytes,
) -> None:
    """Break caught: an accepted-size structural bomb must not allocate one object per line."""
    content = (b"# x" + line_ending) * 262_144
    tracemalloc.start()
    try:
        with pytest.raises(WorkerFailure) as caught:
            ParserRegistry().for_media_type("text/markdown").parse(BytesIO(content))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert peak < 16 * 1024 * 1024


def test_markdown_rejects_the_block_immediately_above_the_output_limit() -> None:
    """Break caught: format logic must enforce the explicit 10,000-block output ceiling."""
    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type("text/markdown").parse(
            BytesIO(b"# x\n" * 10_001)
        )

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
