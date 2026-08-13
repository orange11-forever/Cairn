import re
from collections.abc import Iterable
from io import BytesIO
from typing import Any, BinaryIO, Protocol, cast

from cairn_api.knowledge.schemas import DocxLocator
from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from cairn_worker.parsers import BlockKind, DocumentParser, ParsedBlock, read_parser_source
from cairn_worker.parsers.limits import ensure_block_capacity
from cairn_worker.parsers.office_safety import validate_opc_package

DOCX_MAX_BODY_ELEMENTS = 100_000
DOCX_MAX_TABLE_CELLS = 1_000_000
DOCX_MAX_STYLE_DEPTH = 64
_HEADING_STYLE = re.compile(r"^Heading\s*([1-9])$", re.IGNORECASE)


class _TableCell(Protocol):
    @property
    def paragraphs(self) -> list[Paragraph]: ...


def _style_hidden(style: Any | None) -> bool | None:
    seen: set[object] = set()
    depth = 0
    while style is not None:
        if depth >= DOCX_MAX_STYLE_DEPTH:
            raise ValueError("DOCX style inheritance exceeds parser work limit")
        style_id = cast(str | None, getattr(style, "style_id", None))
        identity: object = style_id if style_id is not None else id(style)
        if identity in seen:
            raise ValueError("DOCX style inheritance contains a cycle")
        seen.add(identity)
        depth += 1
        if style.font.hidden is not None:
            return bool(style.font.hidden)
        style = style.base_style
    return None


def _visible_run_text(run: Run) -> str:
    direct = run.font.hidden
    if direct is not None:
        hidden = direct
    else:
        character_style = _style_hidden(run.style)
        hidden = (
            character_style
            if character_style is not None
            else _style_hidden(
                cast(Any, run._parent).style  # pyright: ignore[reportPrivateUsage]
            )
        )
    return "" if hidden else run.text


def _visible_paragraph_text(paragraph: Paragraph) -> str:
    parts: list[str] = []
    paragraph_element = cast(Any, paragraph._p)  # pyright: ignore[reportPrivateUsage]

    def walk(element: Any) -> None:
        local = element.tag.rsplit("}", 1)[-1]
        if local in {"del", "moveFrom"}:
            return
        if local == "r":
            parts.append(_visible_run_text(Run(element, paragraph)))
            return
        for child in element.iterchildren():
            walk(child)

    for child in paragraph_element.iterchildren():
        walk(child)
    return "".join(parts)


def _cell_text(cell: _TableCell, work: list[int]) -> str:
    segments: list[str] = []

    def walk(element: Any) -> None:
        local = element.tag.rsplit("}", 1)[-1]
        if local in {"del", "moveFrom"}:
            return
        if isinstance(element, CT_P):
            text = _visible_paragraph_text(Paragraph(element, cast(Any, cell))).strip()
        elif isinstance(element, CT_Tbl):
            text = _table_text(Table(element, cast(Any, cell)), work)
        else:
            for child in element.iterchildren():
                walk(child)
            return
        if text:
            segments.append(text)

    for element in cast(Any, cell)._tc.iterchildren():
        walk(element)
    return "\n".join(segments)


def _table_text(table: Table, work: list[int]) -> str:
    rows: list[str] = []
    seen_cells: set[object] = set()
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            identity = cell._tc  # pyright: ignore[reportPrivateUsage]
            if identity in seen_cells:
                continue
            if work[0] >= DOCX_MAX_TABLE_CELLS:
                raise ValueError("DOCX tables exceed parser work limit")
            seen_cells.add(identity)
            work[0] += 1
            cells.append(_cell_text(cell, work))
        if any(cell.strip() for cell in cells):
            rows.append("\t".join(cells))
    return "\n".join(rows)


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
        def visit(element: object) -> None:
            nonlocal body_elements, paragraph_ordinal, table_ordinal, table_cells, heading_path
            body_elements += 1
            if body_elements > DOCX_MAX_BODY_ELEMENTS:
                raise ValueError("DOCX body exceeds parser work limit")

            if isinstance(element, CT_P):
                paragraph_ordinal += 1
                paragraph = Paragraph(element, document)
                text = _visible_paragraph_text(paragraph).strip()
                if not text:
                    return
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
                current_ordinal = table_ordinal
                work = [table_cells]
                text = _table_text(Table(element, document), work)
                table_cells = work[0]
                if text.strip():
                    ensure_block_capacity(len(blocks))
                    blocks.append(
                        ParsedBlock(
                            kind=BlockKind.TABLE,
                            text=text,
                            locator=_docx_locator(
                                heading_path.copy(),
                                table=current_ordinal,
                            ),
                        )
                    )

        def walk_blocks(element: Any) -> None:
            local = element.tag.rsplit("}", 1)[-1]
            if local in {"del", "moveFrom"}:
                return
            if isinstance(element, CT_P | CT_Tbl):
                visit(element)
                return
            for child in element.iterchildren():
                walk_blocks(child)

        for element in elements:
            walk_blocks(cast(Any, element))
        return blocks


__all__ = ["DocxParser"]
