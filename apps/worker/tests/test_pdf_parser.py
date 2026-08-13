from io import BytesIO

import pytest
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind
from cairn_worker.parsers.pdf import PdfParser
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf._page import PageObject
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
)
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def _searchable_pdf(*page_texts: str) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    pdfmetrics.registerFont(  # pyright: ignore[reportUnknownMemberType]
        UnicodeCIDFont("STSong-Light")
    )
    for text in page_texts:
        font = "STSong-Light" if any(ord(character) > 127 for character in text) else "Helvetica"
        document.setFont(font, 12)
        if text:
            document.drawString(72, 720, text)
        document.showPage()
    document.save()
    return output.getvalue()


def _image_only_pdf() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    image = Image.new("RGB", (8, 8), color=(12, 34, 56))
    document.drawImage(  # pyright: ignore[reportUnknownMemberType]
        ImageReader(image), 72, 700, width=16, height=16
    )
    document.showPage()
    document.save()
    return output.getvalue()


def _encrypted_pdf() -> bytes:
    reader = PdfReader(BytesIO(_searchable_pdf("private encrypted text")))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _write_pdf(writer: PdfWriter) -> bytes:
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _blank_pdf_writer(page_count: int = 1) -> PdfWriter:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    return writer


def _page_tree_root(writer: PdfWriter) -> tuple[IndirectObject, DictionaryObject]:
    root_reference = writer.root_object.raw_get("/Pages")
    assert isinstance(root_reference, IndirectObject)
    root = root_reference.get_object()
    assert isinstance(root, DictionaryObject)
    return root_reference, root


def _deep_page_tree(depth: int) -> bytes:
    writer = _blank_pdf_writer()
    root_reference, root = _page_tree_root(writer)
    child_reference = root.raw_get("/Kids")[0]
    assert isinstance(child_reference, IndirectObject)
    for _ in range(depth):
        node = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Pages"),
                NameObject("/Count"): NumberObject(1),
                NameObject("/Kids"): ArrayObject([child_reference]),
            }
        )
        node_reference = writer._add_object(node)  # pyright: ignore[reportPrivateUsage]
        child = child_reference.get_object()
        assert isinstance(child, DictionaryObject)
        child[NameObject("/Parent")] = node_reference
        child_reference = node_reference
    top = child_reference.get_object()
    assert isinstance(top, DictionaryObject)
    top[NameObject("/Parent")] = root_reference
    root[NameObject("/Kids")] = ArrayObject([child_reference])
    root[NameObject("/Count")] = NumberObject(1)
    return _write_pdf(writer)


def _cyclic_page_tree() -> bytes:
    writer = _blank_pdf_writer()
    root_reference, root = _page_tree_root(writer)
    node = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Pages"),
            NameObject("/Count"): NumberObject(1),
            NameObject("/Kids"): ArrayObject([root_reference]),
            NameObject("/Parent"): root_reference,
        }
    )
    node_reference = writer._add_object(node)  # pyright: ignore[reportPrivateUsage]
    root[NameObject("/Kids")] = ArrayObject([node_reference])
    root[NameObject("/Count")] = NumberObject(1)
    return _write_pdf(writer)


def _nested_wide_page_tree(*, branch_count: int, pages_per_branch: int) -> bytes:
    writer = _blank_pdf_writer(branch_count * pages_per_branch)
    root_reference, root = _page_tree_root(writer)
    page_references = list(root.raw_get("/Kids"))
    branch_references: list[IndirectObject] = []
    for branch_index in range(branch_count):
        start = branch_index * pages_per_branch
        branch_pages = page_references[start : start + pages_per_branch]
        branch = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Pages"),
                NameObject("/Parent"): root_reference,
                NameObject("/Kids"): ArrayObject(branch_pages),
                NameObject("/Count"): NumberObject(pages_per_branch),
            }
        )
        branch_reference = writer._add_object(branch)  # pyright: ignore[reportPrivateUsage]
        branch_references.append(branch_reference)
        for page_reference in branch_pages:
            assert isinstance(page_reference, IndirectObject)
            page = page_reference.get_object()
            assert isinstance(page, DictionaryObject)
            page[NameObject("/Parent")] = branch_reference
    root[NameObject("/Kids")] = ArrayObject(branch_references)
    root[NameObject("/Count")] = NumberObject(branch_count * pages_per_branch)
    return _write_pdf(writer)


def _encrypted_malformed_page_tree() -> bytes:
    writer = _blank_pdf_writer()
    _, root = _page_tree_root(writer)
    root[NameObject("/Kids")] = NumberObject(7)
    writer.encrypt("secret")
    return _write_pdf(writer)


def test_pdf_parser_emits_one_text_block_per_nonblank_page_in_source_order() -> None:
    """Break caught: page text or one-based PDF locators must not be lost or reordered."""
    blocks = PdfParser().parse(BytesIO(_searchable_pdf("English page", "中文页面")))

    assert [block.kind for block in blocks] == [BlockKind.TEXT, BlockKind.TEXT]
    assert [block.text for block in blocks] == ["English page", "中文页面"]
    assert [block.locator.model_dump(by_alias=True) for block in blocks] == [
        {"type": "pdf", "page": 1},
        {"type": "pdf", "page": 2},
    ]


def test_pdf_parser_skips_blank_pages_without_renumbering_later_pages() -> None:
    """Break caught: omitted blank pages must not collapse the source page locator."""
    blocks = PdfParser().parse(BytesIO(_searchable_pdf("first", "", "third")))

    assert [block.text for block in blocks] == ["first", "third"]
    assert [block.locator.model_dump()["page"] for block in blocks] == [1, 3]


def test_pdf_parser_rejects_encryption_before_text_extraction() -> None:
    """Break caught: an encrypted page must never be decrypted or treated as malformed text."""
    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_encrypted_pdf()))

    assert caught.value.code == "encrypted_pdf_unsupported"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "encrypted PDF files are not supported"


@pytest.mark.parametrize(
    "content",
    [_searchable_pdf(""), _image_only_pdf()],
    ids=("empty", "image-only"),
)
def test_pdf_parser_rejects_documents_without_searchable_text(content: bytes) -> None:
    """Break caught: empty or image-only PDFs must not imply OCR support or index success."""
    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(content))

    assert caught.value.code == "no_extractable_text"
    assert caught.value.retryable is False


def test_pdf_parser_converts_malformed_input_to_a_safe_permanent_failure() -> None:
    """Break caught: untrusted pypdf diagnostics must not escape the parser boundary."""
    private_payload = b"%PDF-1.7\nprivate malformed object"

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(private_payload))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"
    assert "private" not in caught.value.safe_detail


def test_pdf_parser_enforces_its_page_work_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Break caught: a tiny PDF with an adversarial page tree must not create unbounded work."""
    from cairn_worker.parsers import pdf as pdf_parser

    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGES", 2)

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_searchable_pdf("one", "two", "three")))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False


def test_pdf_parser_rejects_a_wide_page_tree_before_flattening_or_page_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: the page cap must run before pypdf creates every leaf PageObject."""
    from cairn_worker.parsers import pdf as pdf_parser

    content = _write_pdf(_blank_pdf_writer(257))
    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGES", 8)
    flattened = [False]
    materialized_pages = [0]
    original_flatten = PdfReader._flatten  # pyright: ignore[reportPrivateUsage]
    original_page_init = PageObject.__init__

    def tracking_flatten(self: PdfReader, *args: object, **kwargs: object) -> None:
        flattened[0] = True
        original_flatten(self, *args, **kwargs)  # pyright: ignore[reportArgumentType]

    def tracking_page_init(self: PageObject, *args: object, **kwargs: object) -> None:
        materialized_pages[0] += 1
        original_page_init(self, *args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(PdfReader, "_flatten", tracking_flatten)
    monkeypatch.setattr(PageObject, "__init__", tracking_page_init)

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(content))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert flattened[0] is False
    assert materialized_pages[0] == 0


def test_pdf_parser_rejects_a_deep_page_tree_before_recursive_flattening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: accepted-size one-page trees must not induce unbounded recursion depth."""
    from cairn_worker.parsers import pdf as pdf_parser

    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGE_TREE_DEPTH", 8)
    flattened = [False]
    original_flatten = PdfReader._flatten  # pyright: ignore[reportPrivateUsage]

    def tracking_flatten(self: PdfReader, *args: object, **kwargs: object) -> None:
        flattened[0] = True
        original_flatten(self, *args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(PdfReader, "_flatten", tracking_flatten)
    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_deep_page_tree(16)))

    assert caught.value.code == "parser_failed"
    assert flattened[0] is False


def test_pdf_parser_enforces_the_total_raw_page_tree_node_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a broad internal-node tree must stop before pypdf flattening work."""
    from cairn_worker.parsers import pdf as pdf_parser

    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGE_TREE_NODES", 2)
    flattened = [False]
    original_flatten = PdfReader._flatten  # pyright: ignore[reportPrivateUsage]

    def tracking_flatten(self: PdfReader, *args: object, **kwargs: object) -> None:
        flattened[0] = True
        original_flatten(self, *args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(PdfReader, "_flatten", tracking_flatten)
    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_write_pdf(_blank_pdf_writer(2))))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert flattened[0] is False


def test_pdf_parser_rejects_an_oversized_kids_array_before_per_child_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a wide /Kids array must not allocate work beyond the node budget."""
    from cairn_worker.parsers import pdf as pdf_parser

    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGE_TREE_NODES", 4)
    reference_checks = [0]
    original_reference_key = pdf_parser._reference_key  # pyright: ignore[reportPrivateUsage]

    def tracking_reference_key(reference: IndirectObject, reader: PdfReader) -> tuple[int, int]:
        reference_checks[0] += 1
        return original_reference_key(reference, reader)

    monkeypatch.setattr(pdf_parser, "_reference_key", tracking_reference_key)
    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_write_pdf(_blank_pdf_writer(4_096))))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert reference_checks[0] <= 4


def test_pdf_parser_does_not_queue_nested_wide_tree_beyond_global_node_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: sibling reservations at several levels must share one node budget."""
    from cairn_worker.parsers import pdf as pdf_parser

    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGE_TREE_NODES", 6)
    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGES", 100)
    referenced_nodes: set[tuple[int, int]] = set()
    max_referenced_nodes = [0]
    original_reference_key = pdf_parser._reference_key  # pyright: ignore[reportPrivateUsage]

    def tracking_reference_key(reference: IndirectObject, reader: PdfReader) -> tuple[int, int]:
        key = original_reference_key(reference, reader)
        referenced_nodes.add(key)
        max_referenced_nodes[0] = max(max_referenced_nodes[0], len(referenced_nodes))
        return key

    flattened = [False]

    def tracking_flatten(self: PdfReader, *args: object, **kwargs: object) -> None:
        flattened[0] = True

    monkeypatch.setattr(pdf_parser, "_reference_key", tracking_reference_key)
    monkeypatch.setattr(PdfReader, "_flatten", tracking_flatten)

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_nested_wide_page_tree(branch_count=3, pages_per_branch=4)))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert max_referenced_nodes[0] <= pdf_parser.PDF_MAX_PAGE_TREE_NODES
    assert flattened[0] is False


@pytest.mark.parametrize("target", ["leaf", "intermediate"])
def test_pdf_parser_rejects_inconsistent_exact_parent_references(target: str) -> None:
    """Break caught: leaf and intermediate nodes must belong to their traversed parent."""
    writer = _blank_pdf_writer()
    root_reference, root = _page_tree_root(writer)
    page_reference = root.raw_get("/Kids")[0]
    assert isinstance(page_reference, IndirectObject)
    page = page_reference.get_object()
    assert isinstance(page, DictionaryObject)

    if target == "leaf":
        page[NameObject("/Parent")] = page_reference
    else:
        node = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Pages"),
                NameObject("/Count"): NumberObject(1),
                NameObject("/Kids"): ArrayObject([page_reference]),
                NameObject("/Parent"): page_reference,
            }
        )
        node_reference = writer._add_object(node)  # pyright: ignore[reportPrivateUsage]
        page[NameObject("/Parent")] = node_reference
        root[NameObject("/Kids")] = ArrayObject([node_reference])
        root[NameObject("/Count")] = NumberObject(1)
        assert root_reference != page_reference

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_write_pdf(writer)))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False


def test_pdf_parser_rejects_cyclic_page_tree_references() -> None:
    """Break caught: a raw /Pages cycle must terminate as a safe permanent failure."""
    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_cyclic_page_tree()))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("/Type", NameObject("/Private")),
        ("/Kids", NumberObject(7)),
        ("/Count", NameObject("/One")),
        ("/Count", NumberObject(-1)),
    ],
    ids=("type", "kids", "count-type", "negative-count"),
)
def test_pdf_parser_rejects_malformed_raw_page_tree_fields(
    field: str,
    value: NameObject | NumberObject,
) -> None:
    """Break caught: malformed page-tree types must not reach pypdf's permissive flattener."""
    writer = _blank_pdf_writer()
    _, root = _page_tree_root(writer)
    root[NameObject(field)] = value

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_write_pdf(writer)))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("actual_pages", "declared_pages", "page_limit"),
    [(2, 1, 8), (1, 99, 8), (32, 1, 8)],
    ids=("mismatch-within-limit", "declared-over-limit", "declared-under-limit"),
)
def test_pdf_parser_validates_declared_count_and_actual_leaf_total(
    monkeypatch: pytest.MonkeyPatch,
    actual_pages: int,
    declared_pages: int,
    page_limit: int,
) -> None:
    """Break caught: neither an inflated nor understated untrusted /Count may bypass traversal."""
    from cairn_worker.parsers import pdf as pdf_parser

    writer = _blank_pdf_writer(actual_pages)
    _, root = _page_tree_root(writer)
    root[NameObject("/Count")] = NumberObject(declared_pages)
    monkeypatch.setattr(pdf_parser, "PDF_MAX_PAGES", page_limit)

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_write_pdf(writer)))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False


def test_pdf_parser_keeps_encrypted_precedence_over_malformed_page_tree() -> None:
    """Break caught: raw page-tree validation must not replace the stable encrypted-PDF code."""
    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(_encrypted_malformed_page_tree()))

    assert caught.value.code == "encrypted_pdf_unsupported"
    assert caught.value.retryable is False


def test_pdf_parser_bounds_compressed_page_stream_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a small Flate stream must not decompress without a parser-owned ceiling."""
    from cairn_worker.parsers import pdf as pdf_parser

    monkeypatch.setattr(pdf_parser, "PDF_MAX_DECOMPRESSED_STREAM_BYTES", 128)
    content = _searchable_pdf("x" * 2_000)

    with pytest.raises(WorkerFailure) as caught:
        PdfParser().parse(BytesIO(content))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
