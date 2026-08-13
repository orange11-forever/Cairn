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


def test_html_parser_excludes_nested_comments_from_every_visible_owner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Break caught: special DOM strings must never become indexed or diagnostic text."""
    html = b"""
      <h1>Head<span><!--private heading comment--></span>ing</h1>
      <p>Para<em><!--private paragraph comment--></em>graph</p>
      <ul><li>List<strong><!--private list comment--></strong>item</li></ul>
      <table><tr><td>Cell<span><!--private table comment--></span>text</td></tr></table>
    """

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.HEADING, "Heading"),
        (BlockKind.PARAGRAPH, "Paragraph"),
        (BlockKind.PARAGRAPH, "Listitem"),
        (BlockKind.TABLE, "Celltext"),
    ]
    assert [block.locator for block in blocks] == [
        HtmlLocator(headingPath=["Heading"], block=1),
        HtmlLocator(headingPath=["Heading"], block=2),
        HtmlLocator(headingPath=["Heading"], block=3),
        HtmlLocator(headingPath=["Heading"], block=4),
    ]
    observable = "\n".join(
        [
            *(block.text for block in blocks),
            *(block.locator.model_dump_json(by_alias=True) for block in blocks),
            caplog.text,
        ]
    )
    assert "private" not in observable


@pytest.mark.parametrize(
    "special",
    [
        "<?private processing instruction?>",
        "<![CDATA[private cdata section]]>",
    ],
    ids=("processing-instruction", "cdata"),
)
def test_html_parser_excludes_other_nonvisible_special_strings(special: str) -> None:
    """Break caught: non-comment special strings must not masquerade as visible leaves."""
    html = f"<p>left<span>{special}</span>right</p>".encode()

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, "leftright"),
    ]
    assert "private" not in blocks[0].locator.model_dump_json(by_alias=True)


def test_html_parser_does_not_leak_comment_only_content_on_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Break caught: hidden comment text must not escape through failure diagnostics."""
    private_comment = "private failure comment"

    with pytest.raises(WorkerFailure) as caught:
        ParserRegistry().for_media_type("text/html").parse(
            BytesIO(f"<p><span><!--{private_comment}--></span></p>".encode())
        )

    assert caught.value.code == "no_extractable_text"
    assert caught.value.retryable is False
    assert private_comment not in caught.value.safe_detail
    assert private_comment not in caplog.text


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (b"<p>first<br>second</p>", "first\nsecond"),
        (b"<p><br>first<br></p>", "first"),
        (b"<p>first<br><br>second</p>", "first\n\nsecond"),
        (b"<p>first\r\n<br>second</p>", "first\n\nsecond"),
    ],
    ids=("middle", "edge", "repeated", "normalized-source-newline"),
)
def test_html_parser_represents_paragraph_breaks_deterministically(
    html: bytes,
    expected: str,
) -> None:
    """Break caught: visible line breaks must not collapse adjacent paragraph text."""
    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.PARAGRAPH, expected),
    ]


def test_html_parser_represents_table_cell_break_edges_deterministically() -> None:
    """Break caught: cell line breaks must survive without changing table ownership."""
    html = (
        b"<table><tr><td><br>Alpha<br>Beta<br></td>"
        b"<td>Gamma<br><br>Delta</td></tr></table>"
    )

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.TABLE, "Alpha\nBeta\tGamma\n\nDelta"),
    ]
    assert [block.locator for block in blocks] == [
        HtmlLocator(headingPath=[], block=1),
    ]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("first<br>second", "first\nsecond"),
        ("first<br><br>second", "first\n\nsecond"),
        ("<br>  first  <br>", "first"),
        ("first\r\n<br>second", "first\n\nsecond"),
        (
            (
                "left<!--private comment--><?private instruction?>"
                "<![CDATA[private cdata]]>right"
            ),
            "leftright",
        ),
    ],
    ids=("middle", "repeated", "edges", "source-newline", "special-strings"),
)
def test_html_standalone_code_uses_safe_visible_text(
    body: str,
    expected: str,
) -> None:
    """Break caught: standalone code must preserve breaks without indexing special strings."""
    html = f"<h1>Guide</h1><code>{body}</code>".encode()

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.HEADING, "Guide"),
        (BlockKind.CODE, expected),
    ]
    assert [block.locator for block in blocks] == [
        HtmlLocator(headingPath=["Guide"], block=1),
        HtmlLocator(headingPath=["Guide"], block=2),
    ]
    assert "private" not in "\n".join(block.text for block in blocks)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("first<br>second", "first\nsecond"),
        ("first<br><br>second", "first\n\nsecond"),
        ("<br>  first  <br>", "first"),
        ("first\r\n<br>second", "first\n\nsecond"),
        (
            (
                "left<!--private comment--><?private instruction?>"
                "<![CDATA[private cdata]]>right"
            ),
            "leftright",
        ),
    ],
    ids=("middle", "repeated", "edges", "source-newline", "special-strings"),
)
def test_html_pre_owns_nested_code_safe_visible_text(
    body: str,
    expected: str,
) -> None:
    """Break caught: pre must own nested code once with exact safe visible whitespace."""
    html = f"<h1>Guide</h1><pre><code>{body}</code></pre>".encode()

    blocks = ParserRegistry().for_media_type("text/html").parse(BytesIO(html))

    assert [(block.kind, block.text) for block in blocks] == [
        (BlockKind.HEADING, "Guide"),
        (BlockKind.CODE, expected),
    ]
    assert [block.locator for block in blocks] == [
        HtmlLocator(headingPath=["Guide"], block=1),
        HtmlLocator(headingPath=["Guide"], block=2),
    ]
    assert "private" not in "\n".join(block.text for block in blocks)


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
