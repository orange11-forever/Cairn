import json
import math
import tracemalloc
import unicodedata
from io import BytesIO
from typing import BinaryIO, cast

import pytest
from cairn_api.knowledge.object_store import ObjectStoreUnavailable
from cairn_api.knowledge.schemas import (
    CsvLocator,
    DocxLocator,
    HtmlLocator,
    PdfLocator,
    PptxLocator,
    TextLocator,
    XlsxLocator,
)
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import (
    BlockKind,
    DocumentParser,
    ParsedBlock,
    ParserRegistry,
)

from apps.worker.tests.fixture_factory import (
    ParserFixture,
    parser_contract_fixtures,
    whitespace_parser_fixtures,
)

_DECLARED_LOCATORS = (
    PdfLocator,
    DocxLocator,
    PptxLocator,
    XlsxLocator,
    CsvLocator,
    HtmlLocator,
    TextLocator,
)


class _FailingSource(BytesIO):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self._failure = failure

    def read(self, size: int | None = -1) -> bytes:
        del size
        raise self._failure


@pytest.mark.parametrize("fixture", parser_contract_fixtures())
def test_registered_parsers_emit_deterministic_normalized_contract_blocks(
    fixture: ParserFixture,
) -> None:
    """Break caught: a format parser must not emit unstable, blank, or untyped blocks."""
    parser = ParserRegistry().for_media_type(fixture.media_type)

    first = parser.parse(BytesIO(fixture.content))
    second = parser.parse(BytesIO(fixture.content))

    assert isinstance(first, list)
    assert first == second
    assert tuple(block.kind for block in first) == tuple(
        BlockKind(kind) for kind in fixture.expected_kinds
    )
    assert all(block.text.strip() for block in first)
    assert all(isinstance(block.locator, _DECLARED_LOCATORS) for block in first)
    for block in first:
        assert "\r" not in block.text
        assert "\x00" not in block.text
        assert all(
            unicodedata.category(character) != "Cc" or character in "\t\n"
            for character in block.text
        )
        json.dumps(dict(block.metadata), ensure_ascii=False)
        assert all(isinstance(value, str | int | float | bool) for value in block.metadata.values())
        json.dumps(block.locator.model_dump(by_alias=True), ensure_ascii=False)


@pytest.mark.parametrize(("media_type", "content"), whitespace_parser_fixtures())
def test_registered_parsers_reject_an_all_empty_result(
    media_type: str,
    content: bytes,
) -> None:
    """Break caught: empty documents must become a permanent indexed failure, not success."""
    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type(media_type).parse(BytesIO(content))

    assert caught.value.code == "no_extractable_text"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "document contains no supported extractable text"


@pytest.mark.parametrize("fixture", parser_contract_fixtures())
@pytest.mark.parametrize(
    "failure",
    [
        ObjectStoreUnavailable("private object-store endpoint"),
        OSError("private source path"),
    ],
    ids=("object-store-unavailable", "source-os-error"),
)
def test_registered_parsers_preserve_retryable_source_io_failures(
    fixture: ParserFixture,
    failure: Exception,
) -> None:
    """Break caught: transient source reads must not become permanent content failures."""
    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type(fixture.media_type).parse(_FailingSource(failure))

    assert caught.value.code == "object_store_unavailable"
    assert caught.value.retryable is True
    assert caught.value.safe_detail == "object storage is unavailable"
    assert "private" not in caught.value.safe_detail


class _ExplodingParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        raise ValueError(source.read().decode("utf-8"))


class _InternalOSErrorParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        source.read()
        raise OSError("private parser-library path")


class _MalformedKindParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        del source
        return [
            ParsedBlock(
                kind=cast(BlockKind, "not-a-block-kind"),
                text="visible text",
                locator=TextLocator(
                    type="text",
                    headingPath=[],
                    lineStart=1,
                    lineEnd=1,
                ),
            )
        ]


class _MalformedBlockParser(DocumentParser):
    def __init__(self, block: ParsedBlock) -> None:
        self._block = block

    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        del source
        return [self._block]


def test_parser_exceptions_become_permanent_safe_failures() -> None:
    """Break caught: parser diagnostics must never persist source text or enter retries."""
    source_text = "private source 文档"

    with pytest.raises(WorkerFailure) as caught:
        _ExplodingParser().parse(BytesIO(source_text.encode()))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"
    assert source_text not in caught.value.safe_detail


def test_parser_internal_oserror_is_a_permanent_safe_parser_failure() -> None:
    """Break caught: only source-read I/O failures may be classified as infrastructure."""
    with pytest.raises(WorkerFailure) as caught:
        _InternalOSErrorParser().parse(BytesIO(b"read succeeds"))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"
    assert "private parser-library path" not in caught.value.safe_detail


def test_parser_rejects_a_runtime_invalid_block_kind() -> None:
    """Break caught: annotation-only invalid kinds must not escape the parser boundary."""
    with pytest.raises(WorkerFailure) as caught:
        _MalformedKindParser().parse(BytesIO(b"ignored"))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"


@pytest.mark.parametrize(
    "block",
    [
        ParsedBlock(
            kind=BlockKind.TEXT,
            text="visible",
            locator=cast(TextLocator, object()),
        ),
        ParsedBlock(
            kind=BlockKind.TEXT,
            text="visible",
            locator=TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=1),
            metadata=cast(dict[str, str], ["private non-mapping"]),
        ),
        ParsedBlock(
            kind=BlockKind.TEXT,
            text="visible",
            locator=TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=1),
            metadata={cast(str, 7): "private key"},
        ),
        ParsedBlock(
            kind=BlockKind.TEXT,
            text="visible",
            locator=TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=1),
            metadata=cast(dict[str, str], {"nested": ["private nested"]}),
        ),
        ParsedBlock(
            kind=BlockKind.TEXT,
            text="visible",
            locator=TextLocator(type="text", headingPath=[], lineStart=1, lineEnd=1),
            metadata={"score": math.inf},
        ),
    ],
    ids=("locator", "metadata-mapping", "metadata-key", "metadata-value", "metadata-finite"),
)
def test_parser_rejects_malformed_locator_and_metadata_without_leaking_values(
    block: ParsedBlock,
) -> None:
    """Break caught: malformed parser output must not reach JSON consumers or diagnostics."""
    with pytest.raises(WorkerFailure) as caught:
        _MalformedBlockParser(block).parse(BytesIO(b"ignored"))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"
    assert "private" not in caught.value.safe_detail


class _OversizedSource(BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.requested_size: int | None = None

    def read(self, size: int | None = -1) -> bytes:
        self.requested_size = size
        return b"x" * (50 * 1024 * 1024 + 1)


def test_parser_enforces_the_normal_file_limit_with_one_bounded_read() -> None:
    """Break caught: parsers must not trust upstream size metadata or read without a ceiling."""
    source = _OversizedSource()

    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type("text/plain").parse(source)

    assert source.requested_size == 50 * 1024 * 1024 + 1
    assert caught.value.code == "file_too_large"
    assert caught.value.retryable is False


def test_one_megabyte_plain_text_has_bounded_peak_memory() -> None:
    """Break caught: control normalization must not amplify ordinary text into a huge list."""
    content = b"a\n" * (512 * 1024)
    tracemalloc.start()
    try:
        blocks = ParserRegistry().for_media_type("text/plain").parse(BytesIO(content))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(blocks) == 1
    assert blocks[0].text == content.decode().rstrip("\n")
    assert peak < 16 * 1024 * 1024


def test_registry_rejects_noncanonical_and_unsupported_media_types() -> None:
    """Break caught: parsers must not guess formats from aliases, parameters, or filenames."""
    registry = ParserRegistry()

    for media_type in ("TEXT/PLAIN", "text/plain; charset=utf-8", "application/csv", "notes.md"):
        with pytest.raises(WorkerFailure) as caught:
            registry.for_media_type(media_type)
        assert caught.value.code == "unsupported_media_type"
        assert caught.value.retryable is False
