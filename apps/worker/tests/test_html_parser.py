import tracemalloc
from io import BytesIO

import pytest
from cairn_api.knowledge.schemas import HtmlLocator
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, ParserRegistry


def test_html_parser_extracts_only_visible_ordered_structure() -> None:
    """Break caught: active, nonvisible, and remote HTML content must never enter blocks."""
    html = b"""
    <html><head><style>.secret { display: block }</style></head><body>
      <h1>Guide</h1>
      <p>Read <a href="https://private.example/token">docs</a>
         <img src="https://private.example/a.png" alt="remote diagram"></p>
      <script>steal('private source')</script>
      <noscript>hidden fallback</noscript>
      <svg><text>hidden vector</text></svg>
      <template>hidden template</template>
      <ul><li>First item</li><li>Second item</li></ul>
      <pre><code>safe_call()\r\nnext()</code></pre>
      <table><tr><th>Name</th><th>Value</th></tr><tr><td>\xe4\xb8\xad\xe6\x96\x87</td><td>42</td></tr></table>
    </body></html>
    """

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.HEADING, "Guide"),
        (BlockKind.PARAGRAPH, "Read docs"),
        (BlockKind.PARAGRAPH, "First item"),
        (BlockKind.PARAGRAPH, "Second item"),
        (BlockKind.CODE, "safe_call()\nnext()"),
        (BlockKind.TABLE, "Name\tValue\n中文\t42"),
    ]
    assert [block.locator for block in blocks] == [
        HtmlLocator(headingPath=["Guide"], block=1),
        HtmlLocator(headingPath=["Guide"], block=2),
        HtmlLocator(headingPath=["Guide"], block=3),
        HtmlLocator(headingPath=["Guide"], block=4),
        HtmlLocator(headingPath=["Guide"], block=5),
        HtmlLocator(headingPath=["Guide"], block=6),
    ]
    combined = "\n".join(block.text for block in blocks)
    for forbidden in (
        "private.example",
        "remote diagram",
        "steal",
        "hidden fallback",
        "hidden vector",
        "hidden template",
        "<h1>",
        "<table>",
    ):
        assert forbidden not in combined


def test_html_parser_tolerates_malformed_markup_without_returning_html() -> None:
    """Break caught: recoverable malformed HTML must still produce plain visible text."""
    blocks = ParserRegistry().for_media_type("text/html").parse(
        BytesIO("<h1>标题<p>First <b>bold<p>Second".encode())
    )

    assert blocks[0].kind is BlockKind.HEADING
    assert blocks[0].text == "标题"
    assert any("First bold" in block.text for block in blocks)
    assert all("<" not in block.text and ">" not in block.text for block in blocks)


def test_html_parser_preserves_inline_code_and_removes_common_hidden_subtrees() -> None:
    """Break caught: visible inline code must remain while hidden DOM never enters search."""
    html = b"""
      <p>Run <code>safe_call()</code> now.</p>
      <p hidden>private hidden attr</p>
      <div aria-hidden="TRUE"><p>private aria</p></div>
      <section style=" color:red; DISPLAY : none "><p>private display</p></section>
      <span style="visibility:hidden"><code>private visibility</code></span>
    """

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, "Run safe_call() now."),
    ]


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (b"<p>pre<strong>fix</strong></p>", "prefix"),
        (b"<p>Hello,<em>world</em>!</p>", "Hello,world!"),
        ("<p>中<em>文</em>内容</p>".encode(), "中文内容"),
    ],
    ids=("english-word", "punctuation", "chinese"),
)
def test_html_parser_preserves_source_adjacency_across_inline_markup(
    html: bytes,
    expected: str,
) -> None:
    """Break caught: inline markup must not inject visible separator characters."""
    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, expected),
    ]


@pytest.mark.parametrize("level", range(1, 7), ids=lambda level: f"h{level}")
def test_html_heading_owns_nested_inline_code(level: int) -> None:
    """Break caught: heading code must not produce a second weighted content block."""
    html = f"<h{level}>Use <code>x()</code> now</h{level}>".encode()

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.HEADING, "Use x() now"),
    ]


def test_html_parser_assigns_nested_tables_to_one_deterministic_owner() -> None:
    """Break caught: nested table text must not duplicate through outer and inner blocks."""
    html = b"""
      <table><tr><td>Outer<table><tr><td>Inner</td></tr></table></td></tr></table>
    """

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.TABLE, "Outer"),
        (BlockKind.TABLE, "Inner"),
    ]
    assert [block.locator for block in blocks] == [
        HtmlLocator(headingPath=[], block=1),
        HtmlLocator(headingPath=[], block=2),
    ]


@pytest.mark.parametrize(
    "node",
    [b"<p>x</p>", b"<!--x-->"],
    ids=("tags", "comments"),
)
def test_html_tag_bomb_is_rejected_before_dom_construction(node: bytes) -> None:
    """Break caught: accepted-size tag bombs must fail before BeautifulSoup amplification."""
    content = node * 100_001
    tracemalloc.start()
    try:
        with pytest.raises(WorkerFailure) as caught:
            ParserRegistry().for_media_type("text/html").parse(BytesIO(content))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert peak < 16 * 1024 * 1024


def test_html_normalized_tag_bomb_is_rejected_before_dom_construction() -> None:
    """Break caught: stripped controls must not hide a DOM-amplifying tag bomb."""
    content = (b"<\x0cp>x</p>" + b"a" * 100) * 100_001
    tracemalloc.start()
    try:
        with pytest.raises(WorkerFailure) as caught:
            ParserRegistry().for_media_type("text/html").parse(BytesIO(content))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert peak < 64 * 1024 * 1024
