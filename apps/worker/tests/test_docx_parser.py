import warnings
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind
from cairn_worker.parsers.docx import DocxParser
from docx import Document

from apps.worker.tests.fixture_factory import empty_docx_fixture


def _structured_docx() -> bytes:
    document = Document()
    document.add_heading("Overview", level=1)
    document.add_paragraph()
    paragraph = document.add_paragraph()
    paragraph.add_run("Visible ")
    hidden = paragraph.add_run("private hidden ")
    hidden.font.hidden = True
    paragraph.add_run("世界")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "name"
    table.cell(0, 1).text = "value"
    table.cell(1, 0).text = "alpha"
    table.cell(1, 1).text = "一"
    document.add_heading("Details", level=2)
    document.add_paragraph("Tail")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _append_member(package: bytes, name: str, content: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(package), "r") as source, ZipFile(
        output, "w", compression=ZIP_DEFLATED
    ) as target:
        for member in source.infolist():
            target.writestr(member, source.read(member))
        target.writestr(name, content)
    return output.getvalue()


def _replace_member(package: bytes, name: str, content: bytes) -> bytes:
    return _replace_members(package, {name: content})


def _replace_members(package: bytes, replacements: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(package), "r") as source, ZipFile(
        output, "w", compression=ZIP_DEFLATED
    ) as target:
        for member in source.infolist():
            target.writestr(
                member,
                replacements.get(member.filename, source.read(member)),
            )
    return output.getvalue()


def _duplicate_first_member(package: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(package), "r") as source, ZipFile(
        output, "w", compression=ZIP_DEFLATED
    ) as target:
        members = source.infolist()
        for member in members:
            target.writestr(member, source.read(member))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            target.writestr(members[0].filename, source.read(members[0]))
    return output.getvalue()


def _external_hyperlink_docx() -> bytes:
    document = Document()
    paragraph = document.add_paragraph("Before ")
    paragraph.add_run("Visible link label")
    paragraph.add_run(" after")
    output = BytesIO()
    document.save(output)
    package = output.getvalue()
    with ZipFile(BytesIO(package), "r") as source:
        document_xml = source.read("word/document.xml")
        relationships = source.read("word/_rels/document.xml.rels")
    visible_run = b"<w:r><w:t>Visible link label</w:t></w:r>"
    assert visible_run in document_xml
    document_xml = document_xml.replace(
        visible_run,
        b'<w:hyperlink r:id="rIdExternal"><w:r><w:t>Visible link label</w:t></w:r>'
        b"</w:hyperlink>",
        1,
    )
    relationships = relationships.replace(
        b"</Relationships>",
        b'<Relationship Id="rIdExternal" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        b'Target="https://127.0.0.1:1/private" TargetMode="External"/></Relationships>',
        1,
    )
    return _replace_members(
        package,
        {
            "word/document.xml": document_xml,
            "word/_rels/document.xml.rels": relationships,
        },
    )


def _mark_first_member_encrypted(package: bytes) -> bytes:
    marked = bytearray(package)
    local = marked.find(b"PK\x03\x04")
    central = marked.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    local_flags = int.from_bytes(marked[local + 6 : local + 8], "little") | 1
    central_flags = int.from_bytes(marked[central + 8 : central + 10], "little") | 1
    marked[local + 6 : local + 8] = local_flags.to_bytes(2, "little")
    marked[central + 8 : central + 10] = central_flags.to_bytes(2, "little")
    return bytes(marked)


def test_docx_parser_preserves_body_order_heading_paths_and_exact_ordinals() -> None:
    """Break caught: body XML order and exact paragraph/table locators must stay interleaved."""
    blocks = DocxParser().parse(BytesIO(_structured_docx()))

    assert [block.kind for block in blocks] == [
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.TABLE,
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
    ]
    assert [block.text for block in blocks] == [
        "Overview",
        "Visible 世界",
        "name\tvalue\nalpha\t一",
        "Details",
        "Tail",
    ]
    assert [block.locator.model_dump(by_alias=True) for block in blocks] == [
        {"type": "docx", "headingPath": ["Overview"], "paragraph": 1, "table": None},
        {"type": "docx", "headingPath": ["Overview"], "paragraph": 3, "table": None},
        {"type": "docx", "headingPath": ["Overview"], "paragraph": None, "table": 1},
        {
            "type": "docx",
            "headingPath": ["Overview", "Details"],
            "paragraph": 4,
            "table": None,
        },
        {
            "type": "docx",
            "headingPath": ["Overview", "Details"],
            "paragraph": 5,
            "table": None,
        },
    ]
    locators = [block.locator.model_dump(by_alias=True) for block in blocks]
    assert all((locator["paragraph"] is None) != (locator["table"] is None) for locator in locators)


def test_docx_parser_rejects_an_empty_document() -> None:
    """Break caught: the default empty Word paragraph must not become searchable content."""
    with pytest.raises(WorkerFailure) as caught:
        DocxParser().parse(BytesIO(empty_docx_fixture()))

    assert caught.value.code == "no_extractable_text"


def test_docx_parser_indexes_only_an_external_hyperlinks_visible_label() -> None:
    """Break caught: Word relationship targets must never be fetched or included in text."""
    blocks = DocxParser().parse(BytesIO(_external_hyperlink_docx()))

    assert [block.text for block in blocks] == ["Before Visible link label after"]
    assert "127.0.0.1" not in blocks[0].text


@pytest.mark.parametrize(
    "content",
    [b"not a zip", _replace_member(empty_docx_fixture(), "word/document.xml", b"<broken")],
    ids=("not-opc", "malformed-document-xml"),
)
def test_docx_parser_rejects_malformed_packages_safely(content: bytes) -> None:
    """Break caught: ZIP/XML/library diagnostics must remain a bounded permanent fact."""
    with pytest.raises(WorkerFailure) as caught:
        DocxParser().parse(BytesIO(content))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"


@pytest.mark.parametrize(
    "content",
    [
        _append_member(empty_docx_fixture(), "word/vbaProject.bin", b"private macro"),
        _mark_first_member_encrypted(empty_docx_fixture()),
        _append_member(empty_docx_fixture(), "word/bomb.bin", b"0" * (1024 * 1024)),
        _append_member(empty_docx_fixture(), "../private.xml", b"unsafe"),
    ],
    ids=("macro", "encrypted-entry", "compression-ratio", "unsafe-path"),
)
def test_docx_parser_rejects_hazardous_opc_packages(content: bytes) -> None:
    """Break caught: Office libraries must not open macro, encrypted, bomb, or unsafe packages."""
    with pytest.raises(WorkerFailure) as caught:
        DocxParser().parse(BytesIO(content))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert caught.value.safe_detail == "worker handler or parser failed"


@pytest.mark.parametrize(
    "content",
    [
        _append_member(
            _append_member(empty_docx_fixture(), "EncryptionInfo", b"agile metadata"),
            "EncryptedPackage",
            b"encrypted payload",
        ),
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1EncryptionInfo\x00EncryptedPackage",
        _duplicate_first_member(empty_docx_fixture()),
    ],
    ids=("hybrid-encryption-streams", "ole-encrypted-container", "duplicate-name"),
)
def test_docx_parser_rejects_additional_encryption_and_duplicate_package_signals(
    content: bytes,
) -> None:
    """Break caught: non-flag encryption containers and duplicate names must fail pre-library."""
    with pytest.raises(WorkerFailure) as caught:
        DocxParser().parse(BytesIO(content))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False


def test_docx_parser_rejects_xml_doctype_and_external_entity_declarations() -> None:
    """Break caught: Office XML must never resolve an uploaded local or external entity."""
    package = empty_docx_fixture()
    with ZipFile(BytesIO(package), "r") as source:
        document_xml = source.read("word/document.xml")
    hostile_xml = document_xml.replace(
        b"<w:document",
        b'<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "file:///private">]><w:document',
        1,
    ).replace(b"<w:body>", b"<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p>", 1)

    with pytest.raises(WorkerFailure) as caught:
        DocxParser().parse(BytesIO(_replace_member(package, "word/document.xml", hostile_xml)))

    assert caught.value.code == "parser_failed"
    assert caught.value.retryable is False
    assert "private" not in caught.value.safe_detail


def test_docx_parser_enforces_opc_entry_and_uncompressed_size_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: central-directory entry and expansion totals must be checked pre-library."""
    from cairn_worker.parsers import office_safety

    content = empty_docx_fixture()
    monkeypatch.setattr(office_safety, "OPC_MAX_ENTRIES", 1)
    with pytest.raises(WorkerFailure) as entries:
        DocxParser().parse(BytesIO(content))
    assert entries.value.code == "parser_failed"

    monkeypatch.setattr(office_safety, "OPC_MAX_ENTRIES", 10_000)
    monkeypatch.setattr(office_safety, "OPC_MAX_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(WorkerFailure) as expansion:
        DocxParser().parse(BytesIO(content))
    assert expansion.value.code == "parser_failed"
