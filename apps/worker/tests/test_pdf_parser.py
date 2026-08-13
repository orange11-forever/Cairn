from io import BytesIO

import pytest
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind
from cairn_worker.parsers.pdf import PdfParser
from PIL import Image
from pypdf import PdfReader, PdfWriter
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
