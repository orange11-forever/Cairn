import csv
from io import StringIO
from typing import BinaryIO

from cairn_api.knowledge.schemas import CsvLocator

from cairn_worker.parsers import BlockKind, DocumentParser, ParsedBlock, normalize_parser_text

CSV_ROWS_PER_BLOCK = 100


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


class CsvParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        reader = csv.reader(StringIO(_decode_csv(source.read()), newline=""), strict=True)
        blocks: list[ParsedBlock] = []
        rows: list[list[str]] = []
        row_start = 1
        row_number = 0

        for row_number, row in enumerate(reader, start=1):
            rows.append(row)
            if len(rows) == CSV_ROWS_PER_BLOCK:
                blocks.append(self._block(rows, row_start, row_number))
                rows = []
                row_start = row_number + 1
        if rows:
            blocks.append(self._block(rows, row_start, row_number))
        return blocks

    @staticmethod
    def _block(rows: list[list[str]], row_start: int, row_end: int) -> ParsedBlock:
        return ParsedBlock(
            kind=BlockKind.SHEET_ROWS,
            text=_render_rows(rows),
            locator=CsvLocator.model_validate({"rowStart": row_start, "rowEnd": row_end}),
        )


__all__ = ["CSV_ROWS_PER_BLOCK", "CsvParser"]
