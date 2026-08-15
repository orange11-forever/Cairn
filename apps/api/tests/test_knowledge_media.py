from collections.abc import Collection

import pytest
from cairn_api.knowledge.media import (
    ARCHIVE_MAX_BYTES,
    NORMAL_FILE_MAX_BYTES,
    TOP_LEVEL_FILE_LIMIT,
    MediaValidationError,
    validate_upload_intent,
    verify_signature,
)


@pytest.mark.parametrize(
    ("file_name", "declared_media_type", "canonical_media_type"),
    [
        ("REPORT.PDF", "APPLICATION/PDF", "application/pdf"),
        (
            "brief.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "deck.PPTX",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (
            "sheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("rows.csv", "text/csv; charset=utf-8", "text/csv"),
        ("page.htm", "text/html", "text/html"),
        ("notes.txt", "text/plain", "text/plain"),
        ("README.MARKDOWN", "text/x-markdown", "text/markdown"),
        ("bundle.zip", "application/x-zip-compressed", "application/zip"),
    ],
)
def test_validate_upload_intent_normalizes_supported_extensions_and_media_types(
    file_name: str,
    declared_media_type: str,
    canonical_media_type: str,
) -> None:
    descriptor = validate_upload_intent(
        file_name=file_name,
        declared_media_type=declared_media_type,
        size_bytes=1,
    )

    assert descriptor.extension == "." + file_name.rsplit(".", 1)[-1].lower()
    assert descriptor.media_type == canonical_media_type
    assert descriptor.is_archive is file_name.lower().endswith(".zip")


def test_upload_limits_are_exact_and_archive_uses_the_larger_boundary() -> None:
    assert TOP_LEVEL_FILE_LIMIT == 20
    assert NORMAL_FILE_MAX_BYTES == 50 * 1024 * 1024
    assert ARCHIVE_MAX_BYTES == 100 * 1024 * 1024

    assert (
        validate_upload_intent(
            file_name="last-byte.txt",
            declared_media_type="text/plain",
            size_bytes=NORMAL_FILE_MAX_BYTES,
        ).max_bytes
        == NORMAL_FILE_MAX_BYTES
    )
    assert (
        validate_upload_intent(
            file_name="last-byte.zip",
            declared_media_type="application/zip",
            size_bytes=ARCHIVE_MAX_BYTES,
        ).max_bytes
        == ARCHIVE_MAX_BYTES
    )


@pytest.mark.parametrize(
    "file_name",
    ["", "   ", ".", "..", "folder/file.txt", r"folder\file.txt", "bad\x00name.txt"],
)
def test_validate_upload_intent_rejects_empty_or_unsafe_names(file_name: str) -> None:
    with pytest.raises(MediaValidationError) as caught:
        validate_upload_intent(
            file_name=file_name,
            declared_media_type="text/plain",
            size_bytes=1,
        )

    assert caught.value.code == "unsupported_media_type"


@pytest.mark.parametrize(
    ("file_name", "declared_media_type"),
    [
        ("legacy.doc", "application/msword"),
        ("report.pdf", "text/plain"),
        ("notes.txt", "application/octet-stream"),
        ("bundle.zip", "application/pdf"),
    ],
)
def test_validate_upload_intent_rejects_unsupported_or_mismatched_media(
    file_name: str,
    declared_media_type: str,
) -> None:
    with pytest.raises(MediaValidationError) as caught:
        validate_upload_intent(
            file_name=file_name,
            declared_media_type=declared_media_type,
            size_bytes=1,
        )

    assert caught.value.code in {"unsupported_media_type", "upload_media_type_mismatch"}


@pytest.mark.parametrize(
    ("file_name", "media_type", "size_bytes"),
    [
        ("empty.txt", "text/plain", 0),
        ("too-large.txt", "text/plain", NORMAL_FILE_MAX_BYTES + 1),
        ("too-large.zip", "application/zip", ARCHIVE_MAX_BYTES + 1),
    ],
)
def test_validate_upload_intent_rejects_empty_and_oversized_files(
    file_name: str,
    media_type: str,
    size_bytes: int,
) -> None:
    with pytest.raises(MediaValidationError) as caught:
        validate_upload_intent(
            file_name=file_name,
            declared_media_type=media_type,
            size_bytes=size_bytes,
        )

    assert caught.value.code == "file_too_large"


def _verify(
    *,
    file_name: str,
    media_type: str,
    prefix: bytes,
    opc_members: Collection[str] = (),
) -> None:
    descriptor = validate_upload_intent(
        file_name=file_name,
        declared_media_type=media_type,
        size_bytes=max(1, len(prefix)),
    )
    verify_signature(descriptor=descriptor, prefix=prefix, opc_members=opc_members)


@pytest.mark.parametrize(
    ("file_name", "media_type", "prefix", "opc_members"),
    [
        ("report.pdf", "application/pdf", b"%PDF-1.7\n", ()),
        ("bundle.zip", "application/zip", b"PK\x03\x04payload", ()),
        (
            "brief.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04payload",
            ("[Content_Types].xml", "word/document.xml"),
        ),
        (
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            b"PK\x03\x04payload",
            ("[Content_Types].xml", "ppt/presentation.xml"),
        ),
        (
            "sheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            b"PK\x03\x04payload",
            ("[Content_Types].xml", "xl/workbook.xml"),
        ),
        ("notes.txt", "text/plain", "可检索文本".encode(), ()),
        ("rows.csv", "text/csv", "名称,数量\n咖啡,2".encode("gb18030"), ()),
    ],
)
def test_verify_signature_accepts_authoritative_binary_opc_and_text_signatures(
    file_name: str,
    media_type: str,
    prefix: bytes,
    opc_members: Collection[str],
) -> None:
    _verify(
        file_name=file_name,
        media_type=media_type,
        prefix=prefix,
        opc_members=opc_members,
    )


@pytest.mark.parametrize(
    ("file_name", "media_type", "prefix", "opc_members"),
    [
        ("report.pdf", "application/pdf", b"not a pdf", ()),
        ("bundle.zip", "application/zip", b"not a zip", ()),
        (
            "brief.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04payload",
            ("[Content_Types].xml", "ppt/presentation.xml"),
        ),
        (
            "brief.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04payload",
            ("[Content_Types].xml", "word/not-a-document.bin"),
        ),
        (
            "brief.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04payload",
            ("[Content_Types].xml", r"word\document.xml"),
        ),
        ("notes.txt", "text/plain", b"hello\x00hidden", ()),
        ("notes.txt", "text/plain", b"\xff\xfe\x00\x00", ()),
    ],
)
def test_verify_signature_rejects_spoofed_or_implausible_content(
    file_name: str,
    media_type: str,
    prefix: bytes,
    opc_members: Collection[str],
) -> None:
    with pytest.raises(MediaValidationError) as caught:
        _verify(
            file_name=file_name,
            media_type=media_type,
            prefix=prefix,
            opc_members=opc_members,
        )

    assert caught.value.code == "upload_media_type_mismatch"
    assert repr(caught.value) == "MediaValidationError(code='upload_media_type_mismatch')"
    assert "hello" not in str(caught.value)
