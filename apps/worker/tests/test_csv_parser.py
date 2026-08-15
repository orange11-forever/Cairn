import csv
import tracemalloc
from io import BytesIO

import pytest
from cairn_api.knowledge.schemas import CsvLocator
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, ParserRegistry


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_csv_parser_accepts_utf8_with_optional_bom(bom: bytes) -> None:
    """Break caught: supported UTF-8 CSV variants must not expose a BOM as cell content."""
    blocks = ParserRegistry().for_media_type("text/csv").parse(
        BytesIO(bom + "name,value\r\n中文,42".encode())
    )

    assert len(blocks) == 1
    assert blocks[0].kind is BlockKind.SHEET_ROWS
    assert blocks[0].text == "name,value\n中文,42"
    assert blocks[0].locator == CsvLocator(rowStart=1, rowEnd=2)


def test_csv_parser_accepts_strict_gb18030() -> None:
    """Break caught: legacy Chinese CSV content must decode without replacement characters."""
    blocks = ParserRegistry().for_media_type("text/csv").parse(
        BytesIO("名称,数值\r\n温度,二十".encode("gb18030"))
    )

    assert blocks[0].text == "名称,数值\n温度,二十"
    assert blocks[0].locator == CsvLocator(rowStart=1, rowEnd=2)


def test_csv_parser_preserves_quoted_newlines_and_ragged_logical_rows() -> None:
    """Break caught: quoted physical lines must remain one logical row and ragged rows stay valid."""
    content = b'name,note\r\nAlice,"line one\r\nline two"\r\nBob\r\n'

    blocks = ParserRegistry().for_media_type("text/csv").parse(BytesIO(content))

    assert len(blocks) == 1
    assert blocks[0].text == 'name,note\nAlice,"line one\nline two"\nBob'
    assert blocks[0].locator == CsvLocator(rowStart=1, rowEnd=3)


def test_csv_parser_emits_bounded_ordered_row_groups() -> None:
    """Break caught: a large CSV must not become one unbounded in-memory parsed block."""
    content = "\n".join(f"row-{row}" for row in range(1, 206)).encode()

    blocks = ParserRegistry().for_media_type("text/csv").parse(BytesIO(content))

    assert [block.locator for block in blocks] == [
        CsvLocator(rowStart=1, rowEnd=100),
        CsvLocator(rowStart=101, rowEnd=200),
        CsvLocator(rowStart=201, rowEnd=205),
    ]
    assert blocks[0].text.splitlines() == [f"row-{row}" for row in range(1, 101)]
    assert blocks[-1].text.splitlines() == [f"row-{row}" for row in range(201, 206)]


def test_csv_parser_classifies_undecodable_input_safely() -> None:
    """Break caught: bad CSV must be permanent and must not leak source bytes in diagnostics."""
    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type("text/csv").parse(
            BytesIO(b'private,"unterminated\xff')
        )

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert "private" not in caught.value.safe_detail


def test_csv_parser_strictly_rejects_valid_utf8_malformed_quoting() -> None:
    """Break caught: removing strict CSV parsing must not accept an unterminated quote."""
    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type("text/csv").parse(
            BytesIO(b'name,note\nAlice,"private unterminated')
        )

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert "private" not in caught.value.safe_detail


def test_csv_parser_accepts_a_field_above_pythons_implicit_default_limit() -> None:
    """Break caught: valid accepted-size CSV fields must not depend on Python's 128 KiB default."""
    field = "x" * 131_073

    blocks = ParserRegistry().for_media_type("text/csv").parse(BytesIO(field.encode()))

    assert blocks[0].text == field
    assert blocks[0].locator == CsvLocator(rowStart=1, rowEnd=1)
    assert csv.field_size_limit() == 50 * 1024 * 1024


@pytest.mark.parametrize("row", [b"x", b'x"y'], ids=("plain", "literal-quote"))
def test_csv_row_bomb_is_rejected_before_row_and_block_amplification(row: bytes) -> None:
    """Break caught: accepted-size CSV must not allocate beyond the output-block policy."""
    content = (row + b"\n") * 1_000_001
    tracemalloc.start()
    try:
        with pytest.raises(WorkerFailure) as caught:
            ParserRegistry().for_media_type("text/csv").parse(BytesIO(content))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert peak < 24 * 1024 * 1024
