import math
from datetime import date, datetime, time
from io import BytesIO
from typing import BinaryIO

from cairn_api.knowledge.schemas import XlsxLocator
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from cairn_worker.parsers import BlockKind, DocumentParser, ParsedBlock, read_parser_source
from cairn_worker.parsers.limits import ensure_block_capacity
from cairn_worker.parsers.office_safety import validate_opc_package

XLSX_ROWS_PER_BLOCK = 50
XLSX_MAX_SHEETS = 1_000
XLSX_MAX_SOURCE_ROW = 100_000
XLSX_MAX_SOURCE_COLUMN = 4_096
XLSX_MAX_DIMENSION_CELLS = 2_000_000


def _displayed_scalar(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite spreadsheet number")
        return str(value)
    if isinstance(value, str):
        return value
    return None


def _sheet_bounds(worksheet: Worksheet) -> tuple[int, int, int, int]:
    dimension = worksheet.calculate_dimension()
    min_column, min_row, max_column, max_row = range_boundaries(dimension)
    if None in (min_column, min_row, max_column, max_row):
        raise ValueError("invalid worksheet dimension")
    assert min_column is not None
    assert min_row is not None
    assert max_column is not None
    assert max_row is not None
    if (
        max_row > XLSX_MAX_SOURCE_ROW
        or max_column > XLSX_MAX_SOURCE_COLUMN
        or (max_row - min_row + 1) * (max_column - min_column + 1)
        > XLSX_MAX_DIMENSION_CELLS
    ):
        raise ValueError("worksheet dimension exceeds parser work limit")
    return min_column, min_row, max_column, max_row


def _sheet_block(
    *,
    sheet_name: str,
    rows: list[tuple[int, dict[int, str]]],
) -> ParsedBlock:
    min_column = min(column for _, values in rows for column in values)
    max_column = max(column for _, values in rows for column in values)
    row_start = rows[0][0]
    row_end = rows[-1][0]
    text = "\n".join(
        "\t".join(values.get(column, "") for column in range(min_column, max_column + 1))
        for _, values in rows
    )
    return ParsedBlock(
        kind=BlockKind.SHEET_ROWS,
        text=text,
        locator=XlsxLocator.model_validate(
            {
                "sheet": sheet_name,
                "cellRange": (
                    f"{get_column_letter(min_column)}{row_start}:"
                    f"{get_column_letter(max_column)}{row_end}"
                ),
            }
        ),
    )


class XlsxParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        content = read_parser_source(source)
        validate_opc_package(content, required_member="xl/workbook.xml")
        workbook = load_workbook(
            BytesIO(content),
            read_only=True,
            data_only=True,
            keep_links=False,
        )
        try:
            if len(workbook.worksheets) > XLSX_MAX_SHEETS:
                raise ValueError("workbook sheet count exceeds parser work limit")
            blocks: list[ParsedBlock] = []
            for worksheet in workbook.worksheets:
                min_column, min_row, max_column, max_row = _sheet_bounds(worksheet)
                rows: list[tuple[int, dict[int, str]]] = []
                for row_number, cells in enumerate(
                    worksheet.iter_rows(
                        min_row=min_row,
                        max_row=max_row,
                        min_col=min_column,
                        max_col=max_column,
                    ),
                    start=min_row,
                ):
                    values: dict[int, str] = {}
                    for cell in cells:
                        displayed = _displayed_scalar(cell.value)
                        if (
                            displayed is not None
                            and displayed.strip()
                            and isinstance(cell.column, int)
                        ):
                            values[cell.column] = displayed
                    if not values:
                        continue
                    rows.append((row_number, values))
                    if len(rows) == XLSX_ROWS_PER_BLOCK:
                        ensure_block_capacity(len(blocks))
                        blocks.append(_sheet_block(sheet_name=worksheet.title, rows=rows))
                        rows = []
                if rows:
                    ensure_block_capacity(len(blocks))
                    blocks.append(_sheet_block(sheet_name=worksheet.title, rows=rows))
            return blocks
        finally:
            workbook.close()


__all__ = ["XlsxParser"]
