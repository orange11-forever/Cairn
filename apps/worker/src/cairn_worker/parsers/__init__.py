import math
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import BinaryIO, cast

from cairn_api.knowledge.media import SupportedMediaType
from cairn_api.knowledge.object_store import ObjectStoreUnavailable
from cairn_api.knowledge.schemas import (
    CsvLocator,
    DocxLocator,
    HtmlLocator,
    KnowledgeLocator,
    PdfLocator,
    PptxLocator,
    TextLocator,
    XlsxLocator,
)
from pydantic import TypeAdapter

from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers.limits import (
    MAX_PARSED_BLOCKS,
    PARSER_READ_CHUNK_BYTES,
    PARSER_SOURCE_MAX_BYTES,
)


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    SLIDE = "slide"
    SHEET_ROWS = "sheet_rows"
    CODE = "code"
    TEXT = "text"


ScalarMetadata = str | int | float | bool


def _empty_metadata() -> dict[str, ScalarMetadata]:
    return {}


@dataclass(frozen=True)
class ParsedBlock:
    kind: BlockKind
    text: str
    locator: KnowledgeLocator
    metadata: Mapping[str, ScalarMetadata] = field(default_factory=_empty_metadata)


_LOCATOR_TYPES = (
    PdfLocator,
    DocxLocator,
    PptxLocator,
    XlsxLocator,
    CsvLocator,
    HtmlLocator,
    TextLocator,
)
_LOCATOR_ADAPTER: TypeAdapter[KnowledgeLocator] = TypeAdapter(KnowledgeLocator)

_DISALLOWED_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def normalize_parser_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _DISALLOWED_CONTROLS.sub("", normalized)


def decode_utf8_text(content: bytes) -> str:
    return normalize_parser_text(content.decode("utf-8-sig", errors="strict"))


def read_parser_source(source: BinaryIO) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        remaining_with_sentinel = PARSER_SOURCE_MAX_BYTES - total_bytes + 1
        requested_bytes = min(PARSER_READ_CHUNK_BYTES, remaining_with_sentinel)
        try:
            chunk = cast(object, source.read(requested_bytes))
        except (ObjectStoreUnavailable, OSError):
            raise WorkerFailure.for_code("object_store_unavailable", "") from None
        if not isinstance(chunk, bytes):
            raise TypeError("parser source returned non-bytes content")
        if not chunk:
            return b"".join(chunks)
        total_bytes += len(chunk)
        if total_bytes > PARSER_SOURCE_MAX_BYTES:
            raise WorkerFailure.for_code("file_too_large", "")
        chunks.append(chunk)


def _validated_metadata(metadata: object) -> dict[str, ScalarMetadata]:
    if not isinstance(metadata, Mapping):
        raise TypeError("parser returned invalid metadata")
    values = cast(Mapping[object, object], metadata)
    validated: dict[str, ScalarMetadata] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str | int | float | bool):
            raise TypeError("parser returned invalid metadata")
        if isinstance(value, float) and not math.isfinite(value):
            raise TypeError("parser returned invalid metadata")
        validated[key] = value
    return validated


def _validated_locator(locator: object) -> KnowledgeLocator:
    if not isinstance(locator, _LOCATOR_TYPES):
        raise TypeError("parser returned an invalid locator")
    validated = _LOCATOR_ADAPTER.validate_python(
        locator.model_dump(by_alias=True, warnings="none")
    )
    if isinstance(validated, TextLocator) and validated.line_start > validated.line_end:
        raise ValueError("parser returned a reversed text range")
    if isinstance(validated, CsvLocator) and validated.row_start > validated.row_end:
        raise ValueError("parser returned a reversed CSV range")
    return validated


class DocumentParser(ABC):
    def parse(self, source: BinaryIO) -> list[ParsedBlock]:
        try:
            parsed = self._parse(source)
            if len(parsed) > MAX_PARSED_BLOCKS:
                raise ValueError("parser returned too many blocks")
            blocks: list[ParsedBlock] = []
            for candidate in cast(list[object], parsed):
                if not isinstance(candidate, ParsedBlock):
                    raise TypeError("parser returned an invalid block")
                kind = cast(object, candidate.kind)
                if not isinstance(kind, BlockKind):
                    raise TypeError("parser returned an invalid block kind")
                locator = _validated_locator(cast(object, candidate.locator))
                metadata = _validated_metadata(candidate.metadata)
                text = normalize_parser_text(candidate.text).strip("\n")
                if text.strip():
                    blocks.append(
                        ParsedBlock(
                            kind=kind,
                            text=text,
                            locator=locator,
                            metadata=metadata,
                        )
                    )
            if not blocks:
                raise WorkerFailure.for_code("no_extractable_text", "")
            return blocks
        except WorkerFailure:
            raise
        except Exception:  # noqa: BLE001 -- convert every parser failure to a bounded fact.
            raise WorkerFailure("parser_failed", "", retryable=False) from None

    @abstractmethod
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        raise NotImplementedError


class ParserRegistry:
    def __init__(self) -> None:
        from cairn_worker.parsers.csv import CsvParser
        from cairn_worker.parsers.html import HtmlParser
        from cairn_worker.parsers.text import MarkdownParser, TextParser

        self._parsers: Mapping[str, DocumentParser] = {
            SupportedMediaType.TEXT.value: TextParser(),
            SupportedMediaType.MARKDOWN.value: MarkdownParser(),
            SupportedMediaType.CSV.value: CsvParser(),
            SupportedMediaType.HTML.value: HtmlParser(),
        }

    def for_media_type(self, media_type: str) -> DocumentParser:
        parser = self._parsers.get(media_type)
        if parser is None:
            raise WorkerFailure.for_code("unsupported_media_type", "")
        return parser


__all__ = [
    "BlockKind",
    "DocumentParser",
    "ParsedBlock",
    "ParserRegistry",
    "ScalarMetadata",
    "decode_utf8_text",
    "normalize_parser_text",
    "read_parser_source",
]
