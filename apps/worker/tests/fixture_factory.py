from dataclasses import dataclass


@dataclass(frozen=True)
class ParserFixture:
    media_type: str
    content: bytes
    expected_kinds: tuple[str, ...]


def parser_contract_fixtures() -> tuple[ParserFixture, ...]:
    return (
        ParserFixture(
            media_type="text/plain",
            content="Hello\r\n世界\x00\x01\x7f\x80\x9f".encode(),
            expected_kinds=("text",),
        ),
        ParserFixture(
            media_type="text/markdown",
            content="# 标题\r\n\r\nBody".encode(),
            expected_kinds=("heading", "paragraph"),
        ),
        ParserFixture(
            media_type="text/csv",
            content="name,value\r\n中文,1".encode(),
            expected_kinds=("sheet_rows",),
        ),
        ParserFixture(
            media_type="text/html",
            content=b"<h1>Title</h1><p>Hello</p>",
            expected_kinds=("heading", "paragraph"),
        ),
    )


def whitespace_parser_fixtures() -> tuple[tuple[str, bytes], ...]:
    return (
        ("text/plain", b" \r\n\t"),
        ("text/markdown", b" \r\n\t"),
        ("text/csv", b" \r\n\t"),
        ("text/html", b"<html><body> \r\n\t</body></html>"),
    )
