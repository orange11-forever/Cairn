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

from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers.limits import MAX_PARSED_BLOCKS, PARSER_SOURCE_MAX_BYTES


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

_DISALLOWED_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def normalize_parser_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _DISALLOWED_CONTROLS.sub("", normalized)


def decode_utf8_text(content: bytes) -> str:
    return normalize_parser_text(content.decode("utf-8-sig", errors="strict"))


def read_parser_source(source: BinaryIO) -> bytes:
    try:
        content = cast(object, source.read(PARSER_SOURCE_MAX_BYTES + 1))
    except (ObjectStoreUnavailable, OSError):
        raise WorkerFailure.for_code("object_store_unavailable", "") from None
    if not isinstance(content, bytes):
        raise TypeError("parser source returned non-bytes content")
    if len(content) > PARSER_SOURCE_MAX_BYTES:
        raise WorkerFailure.for_code("file_too_large", "")
    return content


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
                locator = cast(object, candidate.locator)
                if not isinstance(locator, _LOCATOR_TYPES):
                    raise TypeError("parser returned an invalid locator")
                metadata = _validated_metadata(candidate.metadata)
                text = normalize_parser_text(candidate.text).strip("\n")
                if text.strip():
                    blocks.append(
                        ParsedBlock(
                            kind=kind,
                            text=text,
                            locator=candidate.locator,
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
