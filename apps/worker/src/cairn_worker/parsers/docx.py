import re
from collections.abc import Iterable
from io import BytesIO
from typing import BinaryIO, Protocol, cast

from cairn_api.knowledge.schemas import DocxLocator
from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from cairn_worker.parsers import BlockKind, DocumentParser, ParsedBlock, read_parser_source
from cairn_worker.parsers.limits import ensure_block_capacity
from cairn_worker.parsers.office_safety import validate_opc_package

DOCX_MAX_BODY_ELEMENTS = 100_000
DOCX_MAX_TABLE_CELLS = 1_000_000
_HEADING_STYLE = re.compile(r"^Heading\s*([1-9])$", re.IGNORECASE)


class _TableCell(Protocol):
    @property
    def paragraphs(self) -> list[Paragraph]: ...


def _visible_run_text(run: Run) -> str:
    return "" if run.font.hidden is True else run.text


def _visible_paragraph_text(paragraph: Paragraph) -> str:
    parts: list[str] = []
    for item in paragraph.iter_inner_content():
        if isinstance(item, Run):
            parts.append(_visible_run_text(item))
        else:
            assert isinstance(item, Hyperlink)
            parts.extend(_visible_run_text(run) for run in item.runs)
    return "".join(parts)


def _cell_text(cell: _TableCell) -> str:
    paragraphs = [
        text
        for paragraph in cell.paragraphs
        if (text := _visible_paragraph_text(paragraph).strip())
    ]
    return "\n".join(paragraphs)


def _table_text(table: Table) -> tuple[str, int]:
    rows: list[str] = []
    visited_cells = 0
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            visited_cells += 1
            cells.append(_cell_text(cell))
        if any(cell.strip() for cell in cells):
            rows.append("\t".join(cells))
    return "\n".join(rows), visited_cells


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    if style is None:
        return None
    for candidate in (style.style_id, style.name):
        match = _HEADING_STYLE.fullmatch(candidate or "")
        if match is not None:
            return int(match.group(1))
    return None


def _docx_locator(
    heading_path: list[str],
    *,
    paragraph: int | None = None,
    table: int | None = None,
) -> DocxLocator:
    return DocxLocator.model_validate(
        {
            "headingPath": heading_path,
            "paragraph": paragraph,
            "table": table,
        }
    )


class DocxParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        content = read_parser_source(source)
        validate_opc_package(content, required_member="word/document.xml")
        document = Document(BytesIO(content))
        return self._body_blocks(document)

    @staticmethod
    def _body_blocks(document: DocumentObject) -> list[ParsedBlock]:
        blocks: list[ParsedBlock] = []
        heading_path: list[str] = []
        paragraph_ordinal = 0
        table_ordinal = 0
        body_elements = 0
        table_cells = 0

        elements = cast(
            Iterable[object],
            document.element.body.iterchildren(),  # pyright: ignore[reportUnknownMemberType]
        )
        for element in elements:
            body_elements += 1
            if body_elements > DOCX_MAX_BODY_ELEMENTS:
                raise ValueError("DOCX body exceeds parser work limit")

            if isinstance(element, CT_P):
                paragraph_ordinal += 1
                paragraph = Paragraph(element, document)
                text = _visible_paragraph_text(paragraph).strip()
                if not text:
                    continue
                level = _heading_level(paragraph)
                if level is not None:
                    heading_path = [*heading_path[: level - 1], text]
                    kind = BlockKind.HEADING
                else:
                    kind = BlockKind.PARAGRAPH
                ensure_block_capacity(len(blocks))
                blocks.append(
                    ParsedBlock(
                        kind=kind,
                        text=text,
                        locator=_docx_locator(
                            heading_path.copy(),
                            paragraph=paragraph_ordinal,
                        ),
                    )
                )
            elif isinstance(element, CT_Tbl):
                table_ordinal += 1
                text, visited_cells = _table_text(Table(element, document))
                table_cells += visited_cells
                if table_cells > DOCX_MAX_TABLE_CELLS:
                    raise ValueError("DOCX tables exceed parser work limit")
                if not text.strip():
                    continue
                ensure_block_capacity(len(blocks))
                blocks.append(
                    ParsedBlock(
                        kind=BlockKind.TABLE,
                        text=text,
                        locator=_docx_locator(
                            heading_path.copy(),
                            table=table_ordinal,
                        ),
                    )
                )
        return blocks


__all__ = ["DocxParser"]
