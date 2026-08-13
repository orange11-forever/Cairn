from io import BytesIO

from cairn_api.knowledge.schemas import HtmlLocator
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
