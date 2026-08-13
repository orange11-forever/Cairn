import re
from typing import BinaryIO

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from cairn_api.knowledge.schemas import HtmlLocator

from cairn_worker.parsers import (
    BlockKind,
    DocumentParser,
    ParsedBlock,
    decode_utf8_text,
    normalize_parser_text,
    read_parser_source,
)
from cairn_worker.parsers.limits import (
    MAX_HTML_TAG_OPENERS,
    ParserLimitExceeded,
    ensure_block_capacity,
)

_NONVISIBLE_ELEMENTS = ("script", "style", "noscript", "svg", "template")
_STRUCTURAL_ELEMENTS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "code", "table")
_BLOCK_DESCENDANTS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table")
_HIDDEN_STYLE = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)"
    r"(?:\s*!important)?\s*(?:;|$)",
    re.IGNORECASE,
)


def _html_locator(heading_path: list[str], block: int) -> HtmlLocator:
    return HtmlLocator.model_validate({"headingPath": heading_path, "block": block})


def _update_heading_path(path: list[str], level: int, title: str) -> list[str]:
    return [*path[: level - 1], title]


def _block_strings(element: Tag) -> list[str]:
    strings: list[str] = []
    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                strings.append(text)
        elif isinstance(child, Tag) and child.name not in _BLOCK_DESCENDANTS:
            strings.extend(_block_strings(child))
    return strings


def _plain_text(element: Tag) -> str:
    return normalize_parser_text(" ".join(_block_strings(element))).strip()


def _table_text(table: Tag) -> str:
    rows: list[str] = []
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        cells = [
            _plain_text(cell)
            for cell in row.find_all(("th", "td"), recursive=False)
        ]
        if any(cells):
            rows.append("\t".join(cells))
    return "\n".join(rows)


def _count_tag_openers(content: bytes) -> int:
    count = 0
    index = 0
    while index < len(content):
        index = content.find(b"<", index)
        if index < 0:
            break
        candidate = index + 1
        while candidate < len(content) and content[candidate] in b" \t\r\n":
            candidate += 1
        if candidate < len(content) and (
            content[candidate] in b"!?"
            or 65 <= content[candidate] <= 90
            or 97 <= content[candidate] <= 122
        ):
            count += 1
            if count > MAX_HTML_TAG_OPENERS:
                raise ParserLimitExceeded
        index += 1
    return count


def _is_hidden(element: Tag) -> bool:
    if element.has_attr("hidden"):
        return True
    aria_hidden = element.get("aria-hidden")
    if isinstance(aria_hidden, str) and aria_hidden.strip().lower() == "true":
        return True
    style = element.get("style")
    return isinstance(style, str) and _HIDDEN_STYLE.search(style) is not None


class HtmlParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        content = read_parser_source(source)
        _count_tag_openers(content)
        soup = BeautifulSoup(decode_utf8_text(content), "html.parser")
        for element in reversed(soup.find_all(True)):
            if element.name in _NONVISIBLE_ELEMENTS or _is_hidden(element):
                element.decompose()

        blocks: list[ParsedBlock] = []
        heading_path: list[str] = []
        for element in soup.find_all(_STRUCTURAL_ELEMENTS):
            name = element.name
            if name in {"p", "li", "pre", "code"} and element.find_parent("table") is not None:
                continue
            if name == "code" and element.find_parent(("pre", "p", "li")) is not None:
                continue

            if name.startswith("h") and len(name) == 2 and name[1].isdigit():
                text = _plain_text(element)
                if not text:
                    continue
                heading_path = _update_heading_path(heading_path, int(name[1]), text)
                kind = BlockKind.HEADING
            elif name == "table":
                text = _table_text(element)
                kind = BlockKind.TABLE
            elif name in {"pre", "code"}:
                text = normalize_parser_text(element.get_text()).strip()
                kind = BlockKind.CODE
            else:
                text = _plain_text(element)
                kind = BlockKind.PARAGRAPH

            if not text:
                continue
            ensure_block_capacity(len(blocks))
            blocks.append(
                ParsedBlock(
                    kind=kind,
                    text=text,
                    locator=_html_locator(heading_path.copy(), len(blocks) + 1),
                )
            )
        return blocks


__all__ = ["HtmlParser"]
