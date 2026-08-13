import re
from typing import BinaryIO

from cairn_api.knowledge.schemas import TextLocator

from cairn_worker.parsers import (
    BlockKind,
    DocumentParser,
    ParsedBlock,
    decode_utf8_text,
    read_parser_source,
)
from cairn_worker.parsers.limits import (
    MAX_MARKDOWN_LINES,
    ParserLimitExceeded,
    ensure_block_capacity,
)

_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$")
_SETEXT_HEADING = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE_START = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\n]*)$")


def _text_locator(
    *,
    locator_type: str,
    heading_path: list[str],
    line_start: int,
    line_end: int,
) -> TextLocator:
    return TextLocator.model_validate(
        {
            "type": locator_type,
            "headingPath": heading_path,
            "lineStart": line_start,
            "lineEnd": line_end,
        }
    )


class TextParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        text = decode_utf8_text(read_parser_source(source))
        first_offset: int | None = None
        last_offset = 0
        first_line = 0
        last_line = 0
        line_number = 1
        position = 0
        while position <= len(text):
            newline = text.find("\n", position)
            line_end = len(text) if newline < 0 else newline
            if text[position:line_end].strip():
                if first_offset is None:
                    first_offset = position
                    first_line = line_number
                last_offset = line_end
                last_line = line_number
            if newline < 0:
                break
            position = newline + 1
            line_number += 1
        if first_offset is None:
            return []
        return [
            ParsedBlock(
                kind=BlockKind.TEXT,
                text=text[first_offset:last_offset],
                locator=_text_locator(
                    locator_type="text",
                    heading_path=[],
                    line_start=first_line,
                    line_end=last_line,
                ),
            )
        ]


def _atx_heading(line: str) -> tuple[int, str] | None:
    match = _ATX_HEADING.match(line)
    if match is None:
        return None
    title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
    if not title:
        return None
    return len(match.group(1)), title


def _setext_level(line: str) -> int | None:
    match = _SETEXT_HEADING.match(line)
    if match is None:
        return None
    return 1 if match.group(1).startswith("=") else 2


def _fence_start(line: str) -> tuple[str, int, str] | None:
    match = _FENCE_START.match(line)
    if match is None:
        return None
    fence = match.group(1)
    info = match.group(2).strip()
    if fence.startswith("`") and "`" in info:
        return None
    return fence[0], len(fence), info


def _is_fence_end(line: str, marker: str, minimum_length: int) -> bool:
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > 3:
        return False
    candidate = stripped.rstrip(" \t")
    return len(candidate) >= minimum_length and set(candidate) == {marker}


def _update_heading_path(path: list[str], level: int, title: str) -> list[str]:
    return [*path[: level - 1], title]


class MarkdownParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        content = read_parser_source(source)
        line_breaks = (
            content.count(b"\n")
            + content.count(b"\r")
            - content.count(b"\r\n")
        )
        if line_breaks + 1 > MAX_MARKDOWN_LINES:
            raise ParserLimitExceeded
        lines = decode_utf8_text(content).split("\n")
        blocks: list[ParsedBlock] = []
        heading_path: list[str] = []
        index = 0

        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue

            heading = _atx_heading(line)
            if heading is not None:
                level, title = heading
                heading_path = _update_heading_path(heading_path, level, title)
                ensure_block_capacity(len(blocks))
                blocks.append(
                    ParsedBlock(
                        kind=BlockKind.HEADING,
                        text=title,
                        locator=_text_locator(
                            locator_type="markdown",
                            heading_path=heading_path.copy(),
                            line_start=index + 1,
                            line_end=index + 1,
                        ),
                    )
                )
                index += 1
                continue

            fence = _fence_start(line)
            if fence is not None:
                marker, minimum_length, info = fence
                start = index
                index += 1
                code_lines: list[str] = []
                while index < len(lines) and not _is_fence_end(
                    lines[index], marker, minimum_length
                ):
                    code_lines.append(lines[index])
                    index += 1
                if index < len(lines):
                    index += 1
                metadata = {"language": info.split()[0]} if info else {}
                ensure_block_capacity(len(blocks))
                blocks.append(
                    ParsedBlock(
                        kind=BlockKind.CODE,
                        text="\n".join(code_lines),
                        locator=_text_locator(
                            locator_type="markdown",
                            heading_path=heading_path.copy(),
                            line_start=start + 1,
                            line_end=index,
                        ),
                        metadata=metadata,
                    )
                )
                continue

            if index + 1 < len(lines):
                level = _setext_level(lines[index + 1])
                if level is not None:
                    title = line.strip()
                    heading_path = _update_heading_path(heading_path, level, title)
                    ensure_block_capacity(len(blocks))
                    blocks.append(
                        ParsedBlock(
                            kind=BlockKind.HEADING,
                            text=title,
                            locator=_text_locator(
                                locator_type="markdown",
                                heading_path=heading_path.copy(),
                                line_start=index + 1,
                                line_end=index + 2,
                            ),
                        )
                    )
                    index += 2
                    continue

            start = index
            paragraph_lines: list[str] = []
            while index < len(lines) and lines[index].strip():
                if index != start and (
                    _atx_heading(lines[index]) is not None
                    or _fence_start(lines[index]) is not None
                    or (
                        index + 1 < len(lines)
                        and _setext_level(lines[index + 1]) is not None
                    )
                ):
                    break
                paragraph_lines.append(lines[index])
                index += 1
            ensure_block_capacity(len(blocks))
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.PARAGRAPH,
                    text="\n".join(paragraph_lines),
                    locator=_text_locator(
                        locator_type="markdown",
                        heading_path=heading_path.copy(),
                        line_start=start + 1,
                        line_end=index,
                    ),
                )
            )

        return blocks


__all__ = ["MarkdownParser", "TextParser"]
