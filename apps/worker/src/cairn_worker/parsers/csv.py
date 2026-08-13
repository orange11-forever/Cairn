import csv
from io import StringIO
from typing import BinaryIO

from cairn_api.knowledge.schemas import CsvLocator

from cairn_worker.parsers import (
    BlockKind,
    DocumentParser,
    ParsedBlock,
    normalize_parser_text,
    read_parser_source,
)
from cairn_worker.parsers.limits import (
    CSV_FIELD_MAX_BYTES,
    CSV_ROWS_PER_BLOCK,
    MAX_CSV_FIELDS,
    MAX_CSV_LOGICAL_ROWS,
    ParserLimitExceeded,
    ensure_block_capacity,
)

csv.field_size_limit(CSV_FIELD_MAX_BYTES)


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return normalize_parser_text(content.decode(encoding, errors="strict"))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", content, 0, len(content), "unsupported CSV encoding")


def _render_rows(rows: list[list[str]]) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _preflight_csv(text: str) -> None:
    if not text:
        return
    in_quotes = False
    at_field_start = True
    logical_rows = 0
    fields = 1
    index = 0
    while index < len(text):
        character = text[index]
        if in_quotes and character == '"':
            if in_quotes and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            in_quotes = False
        elif at_field_start and character == '"':
            in_quotes = True
            at_field_start = False
        elif not in_quotes and character == ",":
            fields += 1
            at_field_start = True
            if fields > MAX_CSV_FIELDS:
                raise ParserLimitExceeded
        elif not in_quotes and character == "\n":
            logical_rows += 1
            at_field_start = True
            if logical_rows > MAX_CSV_LOGICAL_ROWS:
                raise ParserLimitExceeded
            if index + 1 < len(text):
                fields += 1
                if fields > MAX_CSV_FIELDS:
                    raise ParserLimitExceeded
        elif not in_quotes:
            at_field_start = False
        index += 1
    if text[-1] != "\n":
        logical_rows += 1
    if logical_rows > MAX_CSV_LOGICAL_ROWS:
        raise ParserLimitExceeded


class CsvParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        text = _decode_csv(read_parser_source(source))
        _preflight_csv(text)
        reader = csv.reader(StringIO(text, newline=""), strict=True)
        blocks: list[ParsedBlock] = []
        rows: list[list[str]] = []
        row_start = 1
        row_number = 0

        for row_number, row in enumerate(reader, start=1):
            rows.append(row)
            if len(rows) == CSV_ROWS_PER_BLOCK:
                ensure_block_capacity(len(blocks))
                blocks.append(self._block(rows, row_start, row_number))
                rows = []
                row_start = row_number + 1
        if rows:
            ensure_block_capacity(len(blocks))
            blocks.append(self._block(rows, row_start, row_number))
        return blocks

    @staticmethod
    def _block(rows: list[list[str]], row_start: int, row_end: int) -> ParsedBlock:
        return ParsedBlock(
            kind=BlockKind.SHEET_ROWS,
            text=_render_rows(rows),
            locator=CsvLocator.model_validate({"rowStart": row_start, "rowEnd": row_end}),
        )


__all__ = ["CSV_FIELD_MAX_BYTES", "CSV_ROWS_PER_BLOCK", "CsvParser"]
